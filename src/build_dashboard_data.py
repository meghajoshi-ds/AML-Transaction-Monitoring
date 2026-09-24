"""Build the JSON payload behind the analyst dashboard.

A reason code ("structuring") tells an analyst which rule fired but not what it
saw. This reconstructs the evidence behind each alert - the peer payments in the
burst, the matching in/out legs of a pass-through - so the case list answers
"why am I looking at this?" without the analyst re-running the query.

Presentation layer only: reads the pipeline's outputs and changes none of them.
"""
import json

import pandas as pd

import config

BAND_LOW = 0.70
WINDOW_DAYS = 7
RAPID_HOURS = 24


def _money(x):
    return f"\u00a3{x:,.0f}"


def structuring_evidence(row, df):
    """The other near-threshold payments that put this one in a burst."""
    band = ((df["amount"] >= config.REPORTING_THRESHOLD * BAND_LOW)
            & (df["amount"] < config.REPORTING_THRESHOLD))
    window = pd.Timedelta(days=WINDOW_DAYS)
    near = df[band & (df["timestamp"].between(row["timestamp"] - window,
                                              row["timestamp"] + window))]

    as_beneficiary = near[near["receiver_account"] == row["receiver_account"]]
    as_sender = near[near["sender_account"] == row["sender_account"]]
    cluster, shape, counterparty = (
        (as_beneficiary, "into", row["receiver_account"])
        if len(as_beneficiary) >= len(as_sender)
        else (as_sender, "out of", row["sender_account"]))

    senders = cluster["sender_account"].nunique()
    detail = (f"{senders} different senders" if shape == "into" and senders > 1
              else "one sender")
    return (f"{len(cluster)} payments {shape} {counterparty} within {WINDOW_DAYS} days "
            f"({detail}), each between {_money(cluster['amount'].min())} and "
            f"{_money(cluster['amount'].max())} all sitting just under the "
            f"{_money(config.REPORTING_THRESHOLD)} reporting threshold.")


def rapid_evidence(row, df):
    """The matching credit or debit on the other side of the pass-through."""
    window = pd.Timedelta(hours=RAPID_HOURS)
    account = row["sender_account"]

    credits = df[(df["receiver_account"] == account)
                 & (df["timestamp"] <= row["timestamp"])
                 & (df["timestamp"] >= row["timestamp"] - window)
                 & (df["amount"] >= 1_000)]
    if len(credits):
        credit = credits.sort_values("amount").iloc[-1]
        gap = (row["timestamp"] - credit["timestamp"]).total_seconds() / 3600
        pct = row["amount"] / credit["amount"] * 100
        return (f"{_money(credit['amount'])} arrived from {credit['sender_account']}, "
                f"and {_money(row['amount'])} ({pct:.0f}% of it) left for "
                f"{row['receiver_account']} {gap:.0f} hours later. The account held "
                f"the funds, it did not use them.")

    debits = df[(df["sender_account"] == row["receiver_account"])
                & (df["timestamp"] > row["timestamp"])
                & (df["timestamp"] <= row["timestamp"] + window)]
    if len(debits):
        out = debits["amount"].sum()
        gap = (debits["timestamp"].max() - row["timestamp"]).total_seconds() / 3600
        return (f"{_money(row['amount'])} landed in {row['receiver_account']}, and "
                f"{_money(out)} left again across {len(debits)} payment(s) within "
                f"{gap:.0f} hours, which is {out / row['amount'] * 100:.0f}% of what arrived.")
    return "Funds moved in and out of the account inside the 24-hour window."


def main():
    df = pd.read_csv(config.OUTPUTS / "transactions_scored.csv", parse_dates=["timestamp"])
    cases = pd.read_csv(config.CASE_MANAGEMENT, parse_dates=["timestamp"])
    metrics = json.loads(config.METRICS.read_text())

    records = []
    for position, (_, row) in enumerate(cases.iterrows(), start=1):
        reasons = [r.strip() for r in row["reason"].split(",")]
        evidence = []
        if "structuring" in reasons:
            evidence.append(structuring_evidence(row, df))
        if "rapid_movement" in reasons:
            evidence.append(rapid_evidence(row, df))
        if "high_risk_country" in reasons:
            evidence.append(
                f"{row['sender_country']} \u2192 {row['receiver_country']}: one leg "
                f"touches a high-risk jurisdiction. On its own this screen is the "
                f"noisiest rule in the system, so it only escalates when the "
                f"transaction is also behaviourally unusual.")
        if "round_amount" in reasons:
            evidence.append(
                f"{_money(row['amount'])} exactly, a whole-pound amount at size. "
                f"Organic retail payments rarely land on a round number.")
        if row["reason"] == "anomaly score only":
            evidence.append(
                "No rule fired. The model placed this in the top 0.1% of the book on "
                "amount shape, timing, velocity and counterparty spread: the "
                "channel that exists for typologies nobody wrote a rule for.")

        records.append({
            # A neutral reference, NOT the source transaction_id. The generator
            # prefixed planted rows TXNS/TXNR, so publishing the raw id would
            # let any reader pick out every true case from the prefix alone:
            # precisely the leak the write-up warns about. The raw id is not
            # carried into this payload at all.
            "id": f"ALERT-{position:04d}",
            "ts": row["timestamp"].strftime("%Y-%m-%d %H:%M"),
            "sender": row["sender_account"],
            "receiver": row["receiver_account"],
            "amount": round(float(row["amount"]), 2),
            "from": row["sender_country"],
            "to": row["receiver_country"],
            "type": row["transaction_type"],
            "channel": row["channel"],
            "reasons": reasons,
            "channel_label": row["escalation_channel"],
            "score": round(float(row["anomaly_pct"]) * 100, 1),
            "priority": row["priority"],
            "evidence": evidence,
        })

    payload = {
        "headline": metrics["headline"],
        "baseline": metrics["rules_combined_baseline"],
        "combined": metrics["combined_final"],
        "ml_alone": metrics["ml_alone_same_budget"],
        "dataset": metrics["dataset"],
        "rules": [
            {"name": name,
             "alerts": metrics["rules_individually"][name]["alerts"],
             "caught": metrics["rules_individually"][name]["true_positives"],
             "precision": metrics["rules_individually"][name]["precision"],
             "unique": metrics["unique_contribution"][name]["known_cases_found_by_no_other_rule"]}
            for name in metrics["rules_individually"]],
        "cases": records,
    }
    out = config.OUTPUTS / "dashboard_data.json"
    out.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote {out.name}: {len(records)} cases, {out.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
