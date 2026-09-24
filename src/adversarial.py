"""Step 10 - adversarial testing: attack the system and measure how fast it breaks.

Every threshold in a rule layer is a line a launderer can step around, and the
thresholds here are public in the sense that anyone watching which payments get
questioned can infer them. So the honest question is not "does it catch the
patterns in the file" but "how much does an adapting launderer have to change
before it stops catching them, and what does that cost them?"

Method. The defender's model is fixed: the Isolation Forest and its scaler are
fitted once on the original book, exactly as a bank's model would be trained
before the attacker moves. Each scenario then perturbs only the injected
laundering transactions, re-runs the full detection stack against that altered
book, and measures what still gets caught.

The ground-truth labels and the TXNS/TXNR prefixes ARE used here to locate the
patterns to perturb. That is legitimate for a red-team harness - this file
attacks the system, it is not part of it - and it is why this lives outside the
pipeline.
"""
import json

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

import config
import rules as rules_mod
from ml_layer import build_features, RANDOM_STATE

TIER_B_THRESHOLD = 0.99
ML_ONLY_THRESHOLD = 0.999


# ---------------------------------------------------------------------------
# evasions
# ---------------------------------------------------------------------------

def evade_structuring_amounts(df, labels):
    """Drop below the threshold band.

    The rule watches 70-100% of the GBP 10,000 reporting threshold. Paying in
    at GBP 5,500-6,500 sits under that floor. Cost to the launderer: more
    payments to move the same money, and more accounts to move it through.
    """
    out = df.copy()
    m = _structuring_mask(out, labels)
    rng = np.random.default_rng(RANDOM_STATE)
    out.loc[m, "amount"] = rng.uniform(5_500, 6_500, m.sum()).round(2)
    return out


def evade_structuring_timing(df, labels):
    """Stretch the burst past the 7-day window.

    Same payments into the same beneficiary, re-spaced to 10 days apart. Cost:
    the operation takes months instead of a week.
    """
    out = df.copy()
    m = _structuring_mask(out, labels)
    for _, grp in out[m].groupby("receiver_account", sort=False):
        grp = grp.sort_values("timestamp")
        start = grp["timestamp"].iloc[0]
        out.loc[grp.index, "timestamp"] = [
            start + pd.Timedelta(days=10 * i) for i in range(len(grp))]
    return out.sort_values("timestamp").reset_index(drop=True)


def evade_rapid_timing(df, labels):
    """Let the money rest.

    The rule looks 24 hours ahead of a credit. Each hop is delayed to 30 hours
    after the funds arrive. Cost: days of exposure per hop, with the funds
    sitting in an account that can be frozen.
    """
    out = df.copy()
    m = _rapid_mask(out, labels)
    for idx in out[m].sort_values("timestamp").index:
        row = out.loc[idx]
        credits = out[(out["receiver_account"] == row["sender_account"])
                      & (out["timestamp"] <= row["timestamp"])
                      & (out["timestamp"] >= row["timestamp"] - pd.Timedelta(hours=24))
                      & (out["amount"] >= 1_000)]
        if len(credits):
            out.loc[idx, "timestamp"] = (credits["timestamp"].max()
                                         + pd.Timedelta(hours=30))
    return out.sort_values("timestamp").reset_index(drop=True)


def evade_rapid_passthrough(df, labels):
    """Keep a slice back.

    The rule fires when at least 80% of a credit leaves within the window.
    Moving 70% and leaving the rest to trickle out later stays under it. Cost:
    a real one, in laundered value stranded per hop.
    """
    out = df.copy()
    m = _rapid_mask(out, labels)
    for idx in out[m].index:
        row = out.loc[idx]
        credits = out[(out["receiver_account"] == row["sender_account"])
                      & (out["timestamp"] <= row["timestamp"])
                      & (out["timestamp"] >= row["timestamp"] - pd.Timedelta(hours=24))
                      & (out["amount"] >= 1_000)]
        if len(credits):
            out.loc[idx, "amount"] = round(credits["amount"].max() * 0.70, 2)
    return out


def evade_round_amounts(df, labels):
    """Add pence. The cheapest evasion in the system - it costs nothing."""
    out = df.copy()
    m = (out["amount"] == out["amount"].round(0)) & (out["amount"] >= 1_000)
    out.loc[m, "amount"] = out.loc[m, "amount"] + 0.37
    return out


def evade_everything(df, labels):
    """The patient launderer: every evasion at once."""
    out = evade_structuring_amounts(df, labels)
    out = evade_structuring_timing(out, _relabel(out, labels))
    out = evade_rapid_timing(out, _relabel(out, labels))
    out = evade_rapid_passthrough(out, _relabel(out, labels))
    out = evade_round_amounts(out, _relabel(out, labels))
    return out


def _structuring_mask(df, labels):
    return df["transaction_id"].str.startswith("TXNS")


def _rapid_mask(df, labels):
    return df["transaction_id"].str.startswith("TXNR")


def _relabel(df, labels):
    return df["transaction_id"].map(labels).fillna(0).astype(int)


SCENARIOS = [
    ("No evasion (control)", None,
     "the system as measured in the write-up"),
    ("Structuring: smaller payments", evade_structuring_amounts,
     "pay in at GBP 5.5-6.5k instead of GBP 9-10k"),
    ("Structuring: slower burst", evade_structuring_timing,
     "space the same payments 10 days apart"),
    ("Rapid movement: wait 30 hours", evade_rapid_timing,
     "let the funds rest past the 24-hour window"),
    ("Rapid movement: keep 30% back", evade_rapid_passthrough,
     "move 70% of each credit, not 80%+"),
    ("Round amounts: add pence", evade_round_amounts,
     "GBP 9,000.00 becomes GBP 9,000.37"),
    ("All of the above", evade_everything,
     "a launderer who has worked out every threshold"),
]


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------

def run():
    df = pd.read_csv(config.CLEAN_TRANSACTIONS, parse_dates=["timestamp"])
    truth = (pd.read_csv(config.GROUND_TRUTH).drop_duplicates("transaction_id")
             .set_index("transaction_id")["is_laundering_pattern"])

    # The defender's model, fitted once on the original book and then frozen.
    X0 = build_features(df)
    scaler = StandardScaler().fit(X0)
    model = IsolationForest(n_estimators=300, contamination=0.02,
                            max_samples=min(4096, len(X0)),
                            random_state=RANDOM_STATE, n_jobs=-1)
    model.fit(scaler.transform(X0))
    columns = X0.columns

    results = []
    for name, fn, description in SCENARIOS:
        book = df if fn is None else fn(df.copy(), df["transaction_id"].map(truth))
        labels = book["transaction_id"].map(truth).fillna(0).astype(int)

        fired = rules_mod.apply_all(book)
        X = build_features(book).reindex(columns=columns, fill_value=0.0)
        score = pd.Series(-model.score_samples(scaler.transform(X)), index=book.index)
        pct = score.rank(pct=True)

        tier_a = fired[["structuring", "rapid_movement"]].any(axis=1)
        tier_b = fired[["high_risk_country", "round_amount"]].any(axis=1)
        combined = tier_a | (tier_b & (pct >= TIER_B_THRESHOLD))
        final = combined | ((pct >= ML_ONLY_THRESHOLD) & ~combined)

        n_cases = int(labels.sum())
        caught_rules = int((fired["rule_alert"] & (labels == 1)).sum())
        caught_final = int((final & (labels == 1)).sum())
        # What the model alone would find at the shipped alert budget.
        budget = int(final.sum())
        ml_alone = score >= score.nlargest(max(budget, 1)).min()
        caught_ml = int((ml_alone & (labels == 1)).sum())

        results.append({
            "scenario": name,
            "description": description,
            "known_cases": n_cases,
            "rules_recall": round(caught_rules / n_cases, 4),
            "shipped_recall": round(caught_final / n_cases, 4),
            "shipped_caught": caught_final,
            "shipped_alerts": budget,
            "ml_alone_recall": round(caught_ml / n_cases, 4),
        })
        print(f"{name:34s} rules {caught_rules:>3}/{n_cases}  "
              f"shipped {caught_final:>3}/{n_cases}  ml-alone {caught_ml:>3}/{n_cases}  "
              f"({budget:,} alerts)")

    out = config.OUTPUTS / "adversarial.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out.name}")
    return results


if __name__ == "__main__":
    run()
