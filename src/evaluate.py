"""Steps 5, 7 and 8 - measurement, combination, case management.

The ground-truth file is opened here and nowhere else in the pipeline.
"""
import json

import numpy as np
import pandas as pd

import config
import rules as rules_mod
from ml_layer import fit_score

# Tiering of the rule layer, fixed before any metric was looked at.
# Targeted typologies stand on their own; broad screens need corroboration.
TIER_A = ["structuring", "rapid_movement"]      # auto-escalate
TIER_B = ["high_risk_country", "round_amount"]  # escalate only if anomalous


def score_set(flagged: pd.Series, labels: pd.Series) -> dict:
    """Alert-level confusion metrics for one detection strategy."""
    tp = int((flagged & (labels == 1)).sum())
    fp = int((flagged & (labels == 0)).sum())
    fn = int((~flagged & (labels == 1)).sum())
    alerts = int(flagged.sum())
    return {
        "alerts": alerts,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
        "precision": round(tp / alerts, 4) if alerts else 0.0,
        "false_positive_rate_of_alerts": round(fp / alerts, 4) if alerts else 0.0,
        "alert_rate_of_book": round(alerts / len(labels), 4),
    }


def run():
    df = pd.read_csv(config.CLEAN_TRANSACTIONS, parse_dates=["timestamp"])
    truth_raw = pd.read_csv(config.GROUND_TRUTH)
    # The label file mirrors the raw file, replayed rows included: 60,154 rows
    # but 60,139 distinct ids. Labels never conflict within an id (checked), so
    # collapsing is safe. One of the 15 replayed ids is itself a positive, which
    # is why the honest denominator is 139 distinct cases, not 140 rows.
    truth = truth_raw.drop_duplicates("transaction_id").set_index(
        "transaction_id")["is_laundering_pattern"]
    labels = df["transaction_id"].map(truth).fillna(0).astype(int)

    report = {"dataset": {
        "clean_rows": len(df),
        "positive_rows_in_label_file": int(truth_raw["is_laundering_pattern"].sum()),
        "distinct_positive_transactions": int(truth.sum()),
        "known_positives_surviving_cleaning": int(labels.sum()),
    }}
    # Honest accounting: anything the cleaning step threw away is a case the
    # pipeline can never win back.
    quarantine = pd.read_csv(config.OUTPUTS / "quarantined_rows.csv")
    lost = int(quarantine["transaction_id"].map(truth).fillna(0).sum())
    report["dataset"]["known_positives_lost_in_quarantine"] = lost
    report["dataset"]["recall_ceiling"] = round(
        int(labels.sum()) / int(truth.sum()), 4)
    report["dataset"]["known_positives_lost_note"] = (
        "cases removed by cleaning can never be recovered by any downstream layer")

    # ---- step 5: the rule layer, rule by rule --------------------------
    fired = rules_mod.apply_all(df)
    report["rules_individually"] = {
        name: score_set(fired[name], labels) for name in rules_mod.RULES}
    report["rules_combined_baseline"] = score_set(fired["rule_alert"], labels)

    # Which rules earn their place? A rule that only ever re-finds cases another
    # rule already caught is pure alert volume, whatever its own recall says.
    report["unique_contribution"] = {}
    for name in rules_mod.RULES:
        others = fired[[n for n in rules_mod.RULES if n != name]].any(axis=1)
        only_this = fired[name] & ~others
        report["unique_contribution"][name] = {
            "alerts_only_this_rule_raises": int(only_this.sum()),
            "known_cases_found_by_no_other_rule": int((only_this & (labels == 1)).sum()),
        }

    # ---- step 6/7: anomaly layer and the combination -------------------
    scores, _model, _X = fit_score(df)
    df = df.join(scores)

    tier_a = fired[TIER_A].any(axis=1)
    tier_b = fired[TIER_B].any(axis=1)

    # Calibration sweep: how much of the noisy tier survives corroboration,
    # and what that costs in detection. This curve is the actual deliverable.
    sweep = []
    for pct in [0.50, 0.75, 0.80, 0.90, 0.95, 0.975, 0.99, 0.995, 0.999]:
        corroborated = tier_b & (df["anomaly_pct"] >= pct)
        combined = tier_a | corroborated
        row = score_set(combined, labels)
        row["tier_b_threshold_pct"] = pct
        sweep.append(row)
    report["calibration_sweep"] = sweep

    # Operating point. Pure optimisation ("fewest alerts that still hold
    # baseline recall") degenerates here: the broad screens contribute no
    # unique detections at all, so the optimiser drives their threshold to the
    # top of the grid and effectively deletes them. That is the right answer
    # for this dataset and the wrong answer for a bank - a jurisdiction screen
    # exists partly for regulatory coverage of a typology that may simply be
    # absent from twelve months of synthetic data. So the threshold is a
    # documented policy choice: keep a corroborated jurisdiction channel alive
    # at the top 1% of anomaly score, and report the degenerate optimum beside
    # it so the cost of that caution is visible.
    theta = 0.99
    report["chosen_tier_b_threshold_pct"] = theta
    report["threshold_selection"] = (
        "policy choice, not optimised: retains a corroborated high-risk-country "
        "channel. The volume-minimising alternative is tier_a_only.")

    corroborated = tier_b & (df["anomaly_pct"] >= theta)
    combined = tier_a | corroborated

    report["tier_a_only"] = score_set(tier_a, labels)

    # A small ML-only channel for typologies no rule describes.
    ml_only = (df["anomaly_pct"] >= 0.999) & ~combined
    report["ml_only_channel"] = score_set(ml_only, labels)
    final = combined | ml_only

    report["combined_final"] = score_set(final, labels)

    # ML on its own, sized to the same alert budget, as a control.
    budget = int(final.sum())
    ml_alone = df["anomaly_score"] >= df["anomaly_score"].nlargest(budget).min()
    report["ml_alone_same_budget"] = score_set(ml_alone, labels)

    # ---- the headline numbers ------------------------------------------
    base = report["rules_combined_baseline"]
    comb = report["combined_final"]
    report["headline"] = {
        "baseline_alerts": base["alerts"],
        "combined_alerts": comb["alerts"],
        "alert_volume_reduction_pct": round(
            100 * (base["alerts"] - comb["alerts"]) / base["alerts"], 1),
        "baseline_false_positives": base["false_positives"],
        "combined_false_positives": comb["false_positives"],
        "false_positive_reduction_pct": round(
            100 * (base["false_positives"] - comb["false_positives"]) / base["false_positives"], 1),
        "baseline_recall": base["recall"],
        "combined_recall": comb["recall"],
        "baseline_precision": base["precision"],
        "combined_precision": comb["precision"],
        "analyst_hours_saved_at_15min_per_alert": round(
            (base["alerts"] - comb["alerts"]) * 0.25, 1),
    }

    # ---- step 8: case management view ----------------------------------
    df["rule_reasons"] = fired.apply(rules_mod.reason_text, axis=1)
    df["escalation_channel"] = np.where(
        tier_a, "rule: targeted typology",
        np.where(corroborated, "rule: broad screen + anomaly corroboration",
                 np.where(ml_only, "anomaly only", "")))
    cases = df[final].copy()
    cases["reason"] = np.where(
        cases["rule_reasons"] == "", "anomaly score only", cases["rule_reasons"])
    cases["anomaly_pct"] = cases["anomaly_pct"].round(4)
    cases["priority"] = pd.cut(
        cases["anomaly_pct"], [0, .90, .99, 1.0],
        labels=["low", "medium", "high"], include_lowest=True)
    cases = cases.sort_values(["priority", "anomaly_pct"], ascending=[False, False])
    cols = ["transaction_id", "timestamp", "sender_account", "receiver_account",
            "amount", "sender_country", "receiver_country", "transaction_type",
            "channel", "reason", "escalation_channel", "anomaly_pct", "priority"]
    cases[cols].to_csv(config.CASE_MANAGEMENT, index=False)
    report["case_management"] = {
        "rows": len(cases),
        "by_channel": cases["escalation_channel"].value_counts().to_dict(),
        "by_priority": cases["priority"].value_counts().to_dict(),
    }

    # Persist scored transactions for the figures.
    df["label"] = labels
    df["rule_alert"] = fired["rule_alert"]
    df["final_alert"] = final
    df.to_csv(config.OUTPUTS / "transactions_scored.csv", index=False)

    config.METRICS.write_text(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    rep = run()
    print(json.dumps(rep, indent=2, default=str))
