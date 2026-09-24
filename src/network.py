"""Account-level network analysis.

Everything else in this project scores transactions. Laundering is not a
transaction, it is a structure: money funnelled into a collection account, or
walked through a chain of mules. Scoring one payment at a time means an analyst
sees ten alerts where there is one case.

Two structures are looked for, both visible only in the graph between accounts:

  * FUNNELS  - many distinct senders paying one beneficiary just under the
               reporting threshold. High fan-in concentrated in the threshold
               band, which no single payment looks odd against.
  * CHAINS   - A pays B, B pays C soon after and for a similar amount. Layering
               leaves a path, not a point.

Run: python src/network.py
"""
import json

import numpy as np
import pandas as pd

import config
from timeutils import epoch_ns

BAND_LOW = 0.70
CHAIN_WINDOW_HOURS = 24
CHAIN_TOLERANCE = 0.15      # hop amounts within 15% of each other


def funnel_accounts(df: pd.DataFrame, min_senders: int = 3) -> pd.DataFrame:
    """Beneficiaries taking near-threshold payments from several distinct senders.

    Fan-in on its own is ordinary: a shop has many payers. What is not ordinary
    is fan-in *concentrated just under the reporting threshold*, which is why
    the ratio matters more than the raw count.
    """
    band = ((df["amount"] >= config.REPORTING_THRESHOLD * BAND_LOW)
            & (df["amount"] < config.REPORTING_THRESHOLD))

    inbound = df.groupby("receiver_account").agg(
        inbound_payments=("amount", "size"),
        inbound_total=("amount", "sum"),
        distinct_senders=("sender_account", "nunique"))

    near = df[band].groupby("receiver_account").agg(
        near_threshold_payments=("amount", "size"),
        near_threshold_total=("amount", "sum"),
        near_threshold_senders=("sender_account", "nunique"))

    acc = inbound.join(near).fillna(0)
    acc["share_near_threshold"] = (acc["near_threshold_total"]
                                   / acc["inbound_total"]).round(4)
    acc["is_funnel"] = acc["near_threshold_senders"] >= min_senders
    return acc.sort_values(["is_funnel", "near_threshold_senders", "near_threshold_total"],
                           ascending=False)


def chains(df: pd.DataFrame, min_amount: float = 1_000) -> pd.DataFrame:
    """A -> B -> C hops close in time and similar in size.

    Each hop looks like an ordinary transfer. The path is the pattern.
    """
    t = df.assign(ts=epoch_ns(df["timestamp"]) // 1_000_000_000)
    big = t[t["amount"] >= min_amount]
    window = CHAIN_WINDOW_HOURS * 3600

    hops = big.merge(big, left_on="receiver_account", right_on="sender_account",
                     suffixes=("_in", "_out"))
    hops = hops[(hops["ts_out"] > hops["ts_in"])
                & (hops["ts_out"] <= hops["ts_in"] + window)
                & ((hops["amount_out"] - hops["amount_in"]).abs()
                   <= CHAIN_TOLERANCE * hops["amount_in"])]

    return pd.DataFrame({
        "hop_in": hops["transaction_id_in"],
        "hop_out": hops["transaction_id_out"],
        "origin": hops["sender_account_in"],
        "intermediary": hops["receiver_account_in"],
        "destination": hops["receiver_account_out"],
        "amount_in": hops["amount_in"].round(2),
        "amount_out": hops["amount_out"].round(2),
        "hours_held": ((hops["ts_out"] - hops["ts_in"]) / 3600).round(1),
    }).sort_values("hours_held")


def run():
    df = pd.read_csv(config.CLEAN_TRANSACTIONS, parse_dates=["timestamp"])
    truth = (pd.read_csv(config.GROUND_TRUTH).drop_duplicates("transaction_id")
             .set_index("transaction_id")["is_laundering_pattern"])
    labels = df["transaction_id"].map(truth).fillna(0).astype(int)

    acc = funnel_accounts(df)
    funnels = acc[acc["is_funnel"]]
    ch = chains(df)

    # Evaluation: does an account-level view find the same cases, and how much
    # smaller is the review queue?
    case_accounts = set(df.loc[labels == 1, "receiver_account"])
    structuring_accounts = set(
        df.loc[(labels == 1) & (df["amount"] < config.REPORTING_THRESHOLD),
               "receiver_account"])
    found = structuring_accounts & set(funnels.index)

    chain_txns = set(ch["hop_in"]) | set(ch["hop_out"])
    chain_cases = int(labels[df["transaction_id"].isin(chain_txns)].sum())

    report = {
        "accounts_in_book": int(df["receiver_account"].nunique()),
        "funnel_accounts_flagged": int(len(funnels)),
        "structuring_beneficiary_accounts": len(structuring_accounts),
        "of_those_caught_as_funnels": len(found),
        "funnel_recall": round(len(found) / max(len(structuring_accounts), 1), 4),
        "chain_hops_found": int(len(ch)),
        "chain_transactions": len(chain_txns),
        "known_cases_in_chains": chain_cases,
        "transaction_alerts_for_the_same_ground": int(labels.sum()),
    }

    print("FUNNELS")
    print(f"  {report['funnel_accounts_flagged']} accounts flagged out of "
          f"{report['accounts_in_book']:,} in the book")
    print(f"  {report['of_those_caught_as_funnels']}/"
          f"{report['structuring_beneficiary_accounts']} known structuring "
          f"beneficiaries caught ({report['funnel_recall']:.0%})")
    print("\n  top funnel accounts:")
    print(funnels.head(6)[["distinct_senders", "near_threshold_senders",
                           "near_threshold_payments", "share_near_threshold"]].to_string())
    print(f"\nCHAINS\n  {report['chain_hops_found']} hops across "
          f"{report['chain_transactions']} transactions, "
          f"{report['known_cases_in_chains']} of them known cases")
    if len(ch):
        print("\n  fastest hops:")
        print(ch.head(5).to_string(index=False))

    funnels.to_csv(config.OUTPUTS / "network_funnels.csv")
    ch.to_csv(config.OUTPUTS / "network_chains.csv", index=False)
    (config.OUTPUTS / "network_summary.json").write_text(json.dumps(report, indent=2))
    print(f"\nwrote network_funnels.csv, network_chains.csv, network_summary.json")
    return report


if __name__ == "__main__":
    run()
