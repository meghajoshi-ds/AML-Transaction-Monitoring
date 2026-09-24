"""Step 4 - rule-based detection layer.

One function per typology so each can be measured on its own in evaluate.py.
Every rule takes the cleaned frame and returns a boolean Series aligned to it.
No rule looks at transaction_id or at the labels.
"""
import numpy as np
import pandas as pd

import config
from timeutils import epoch_ns


def _in_burst(times: np.ndarray, window_ns: int, min_count: int) -> np.ndarray:
    """Is each event part of ANY window of `window_ns` holding `min_count` events?

    The subtlety is that a window need not start or end at the event being
    tested - the middle payment of a three-payment burst is in a qualifying
    window without anchoring one. It is enough to consider windows that start
    at an event: any window can be slid right to begin at its first event
    without losing members.

    So: mark every event that starts a qualifying window, then flag event i if
    such a start exists within the preceding `window_ns`. `times` must be sorted.
    """
    idx = np.arange(len(times))
    starts_qualifying_window = (
        np.searchsorted(times, times + window_ns, "right") - idx) >= min_count
    cumulative = np.concatenate([[0], starts_qualifying_window.cumsum()])
    earliest = np.searchsorted(times, times - window_ns, "left")
    return (cumulative[idx + 1] - cumulative[earliest]) > 0


def rule_structuring(df: pd.DataFrame, threshold: int = config.REPORTING_THRESHOLD,
                     band_low: float = 0.70, window_days: int = 7,
                     min_count: int = 3) -> pd.Series:
    """Repeated transactions sitting just under the reporting threshold.

    Classic structuring splits one reportable sum into several sub-threshold
    payments. It is checked on BOTH sides of the transaction: on the sender
    (one customer splitting their own deposit) and on the receiver (several
    senders funnelling into one beneficiary - smurfing). Profiling justified
    the second half: in the 9,000-9,999 band the busiest beneficiary accounts
    take 10-12 payments while no single sender exceeds 4.
    """
    flag = pd.Series(False, index=df.index)
    band = (df["amount"] >= threshold * band_low) & (df["amount"] < threshold)
    sub = df[band]
    window_ns = int(pd.Timedelta(days=window_days).value)

    for side in ("sender_account", "receiver_account"):
        for _, grp in sub.groupby(side, sort=False):
            if len(grp) < min_count:
                continue
            grp = grp.sort_values("timestamp")
            burst = _in_burst(epoch_ns(grp["timestamp"]), window_ns, min_count)
            flag.loc[grp.index[burst]] = True
    return flag


def rule_rapid_movement(df: pd.DataFrame, window_hours: int = 24,
                        passthrough: float = 0.80,
                        min_amount: float = 1_000) -> pd.Series:
    """Money arriving in an account and leaving again almost immediately.

    A pass-through / mule account holds funds briefly. For every credit of at
    least `min_amount`, the debits from the same account in the following
    `window_hours` are summed; if they return at least `passthrough` of the
    credit, both legs are flagged - the analyst needs the pair to see it.
    """
    flag = pd.Series(False, index=df.index)
    window_ns = int(pd.Timedelta(hours=window_hours).value)
    times_ns = pd.Series(epoch_ns(df["timestamp"]), index=df.index)

    inbound = df[df["amount"] >= min_amount]
    for account, credits in inbound.groupby("receiver_account", sort=False):
        debits = df[df["sender_account"] == account]
        if debits.empty:
            continue
        debits = debits.sort_values("timestamp")
        d_times = times_ns.loc[debits.index].to_numpy()
        d_cumsum = np.concatenate([[0.0], debits["amount"].to_numpy().cumsum()])

        for idx, credit in credits.iterrows():
            t0 = times_ns.loc[idx]
            lo = np.searchsorted(d_times, t0, "right")
            hi = np.searchsorted(d_times, t0 + window_ns, "right")
            if hi <= lo:
                continue
            if d_cumsum[hi] - d_cumsum[lo] >= passthrough * credit["amount"]:
                flag.loc[idx] = True
                flag.loc[debits.index[lo:hi]] = True
    return flag


def rule_high_risk_country(df: pd.DataFrame,
                           countries=config.HIGH_RISK_COUNTRIES) -> pd.Series:
    """Either leg of the transaction touches a high-risk jurisdiction."""
    return df["sender_country"].isin(countries) | df["receiver_country"].isin(countries)


def rule_round_amount(df: pd.DataFrame, min_amount: float = 1_000) -> pd.Series:
    """Suspiciously exact amounts.

    Organic retail spending almost never lands on a whole pound at size; hand-
    entered laundering amounts often do.
    """
    return (df["amount"] == df["amount"].round(0)) & (df["amount"] >= min_amount)


RULES = {
    "structuring": rule_structuring,
    "rapid_movement": rule_rapid_movement,
    "high_risk_country": rule_high_risk_country,
    "round_amount": rule_round_amount,
}


def apply_all(df: pd.DataFrame) -> pd.DataFrame:
    """Run every rule, returning one boolean column each plus a total."""
    fired = pd.DataFrame({name: fn(df) for name, fn in RULES.items()}, index=df.index)
    fired["rules_fired"] = fired.sum(axis=1)
    fired["rule_alert"] = fired["rules_fired"] > 0
    return fired


def reason_text(row) -> str:
    """Human-readable reason string for the case management view."""
    names = [r for r in RULES if row[r]]
    return ", ".join(names) if names else ""


if __name__ == "__main__":
    df = pd.read_csv(config.CLEAN_TRANSACTIONS, parse_dates=["timestamp"])
    fired = apply_all(df)
    for name in RULES:
        print(f"{name:20s} {int(fired[name].sum()):>6,} alerts")
    print(f"{'ANY RULE':20s} {int(fired['rule_alert'].sum()):>6,} alerts "
          f"({fired['rule_alert'].mean():.2%} of transactions)")
