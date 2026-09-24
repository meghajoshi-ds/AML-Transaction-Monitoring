"""Step 6 - unsupervised anomaly layer.

Isolation Forest over behavioural features. Deliberately unsupervised: in a
real bank you have no reliable transaction-level laundering labels to train on,
only a backlog of closed alerts.

Two design constraints:
  * No identifier features. transaction_id encodes the answer (TXNS/TXNR) and
    is excluded, as is anything derived from it.
  * No high-risk-country feature. That signal already has its own rule; keeping
    it out of the model means the two layers fail independently, which is the
    whole point of combining them.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

import config
from timeutils import epoch_ns

RANDOM_STATE = 42

# Prior transactions an account needs before its amount z-score is trusted.
MIN_HISTORY = 5


def _velocity(keys: pd.Series, times: pd.Series, window_hours: int) -> np.ndarray:
    """Transactions by the same account in the preceding window."""
    window_ns = int(pd.Timedelta(hours=window_hours).value)
    out = np.zeros(len(keys), dtype=float)
    times_ns = epoch_ns(times)
    order = np.argsort(times_ns, kind="stable")
    k = keys.values[order]
    t = times_ns[order]
    counts = np.zeros(len(k))
    for key in pd.unique(k):
        m = np.flatnonzero(k == key)
        tt = t[m]
        counts[m] = np.arange(len(m)) - np.searchsorted(tt, tt - window_ns, "left")
    out[order] = counts
    return out


def _trailing_distinct(keys: pd.Series, others: pd.Series) -> np.ndarray:
    """Distinct counterparties seen for each key BEFORE the current row.

    Rows must already be in time order. One pass, a set per account.
    """
    seen, out = {}, np.zeros(len(keys), dtype=float)
    for i, (k, o) in enumerate(zip(keys.to_numpy(), others.to_numpy())):
        bucket = seen.setdefault(k, set())
        out[i] = len(bucket)
        bucket.add(o)
    return out


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Behavioural feature matrix - amount shape, timing, velocity, tenure.

    Every account-level feature is computed over the account's history UP TO
    each transaction, never over the whole file. Using full-period statistics
    would score a January transaction partly on the following December's
    behaviour: information no production system has at decision time, and it
    flatters the model. Expanding statistics are shifted by one row so a
    transaction never contributes to its own baseline.
    """
    cust = pd.read_csv(config.CUSTOMERS, parse_dates=["account_open_date"])
    opened = cust.set_index("account_id")["account_open_date"]

    df = df.sort_values("timestamp")
    order = df.index
    f = pd.DataFrame(index=order)
    f["log_amount"] = np.log1p(df["amount"])

    # How unusual is this amount for THIS account, given only its past.
    # min_periods guards against thin history: with two prior transactions the
    # standard deviation can be near zero and the z-score explodes into the
    # thousands, which is noise the model would happily key on.
    g = df.groupby("sender_account")["amount"]
    prior_mean = g.transform(lambda x: x.expanding(min_periods=MIN_HISTORY).mean().shift(1))
    prior_std = g.transform(lambda x: x.expanding(min_periods=MIN_HISTORY).std().shift(1))
    prior_max = g.transform(lambda x: x.expanding().max().shift(1))
    f["amount_z_vs_account"] = ((df["amount"] - prior_mean)
                                / prior_std.replace(0, np.nan)).fillna(0)
    f["amount_vs_account_max"] = (df["amount"] / prior_max).replace(
        [np.inf, -np.inf], np.nan).fillna(1.0)

    f["hour"] = df["hour"]
    f["is_night"] = df["hour"].between(1, 5).astype(int)
    f["day_of_week"] = df["day_of_week"]
    f["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    f["is_cross_border"] = df["is_cross_border"]

    f["sender_velocity_24h"] = _velocity(df["sender_account"], df["timestamp"], 24)
    f["sender_velocity_7d"] = _velocity(df["sender_account"], df["timestamp"], 24 * 7)
    f["receiver_velocity_24h"] = _velocity(df["receiver_account"], df["timestamp"], 24)

    # Account-level context, trailing only.
    f["sender_txn_count"] = df.groupby("sender_account").cumcount()
    f["sender_distinct_counterparties"] = _trailing_distinct(
        df["sender_account"], df["receiver_account"])
    f["receiver_distinct_counterparties"] = _trailing_distinct(
        df["receiver_account"], df["sender_account"])

    tenure = (df["timestamp"] - df["sender_account"].map(opened)).dt.days
    f["sender_account_age_days"] = tenure.fillna(tenure.median())

    # Distance from the reporting threshold - shape, not a country flag.
    f["pct_of_threshold"] = df["amount"] / config.REPORTING_THRESHOLD

    f = pd.get_dummies(
        f.join(df[["transaction_type", "channel"]]),
        columns=["transaction_type", "channel"], drop_first=False)
    return f.astype(float).reindex(df.index).sort_index()


def fit_score(df: pd.DataFrame, contamination: float = 0.02):
    """Fit Isolation Forest and return an anomaly score per transaction.

    Score is oriented so that HIGHER means more anomalous, then converted to a
    percentile so thresholds read as 'top n% weirdest'.
    """
    X = build_features(df)
    Xs = StandardScaler().fit_transform(X)
    model = IsolationForest(
        n_estimators=300, contamination=contamination,
        max_samples=min(4096, len(X)), random_state=RANDOM_STATE, n_jobs=-1)
    model.fit(Xs)
    raw = -model.score_samples(Xs)          # higher = more anomalous
    pct = pd.Series(raw, index=df.index).rank(pct=True)
    return pd.DataFrame({"anomaly_score": raw, "anomaly_pct": pct}, index=df.index), model, X


if __name__ == "__main__":
    df = pd.read_csv(config.CLEAN_TRANSACTIONS, parse_dates=["timestamp"])
    scores, model, X = fit_score(df)
    print(f"features: {X.shape[1]}  rows: {X.shape[0]:,}")
    print(scores["anomaly_score"].describe().round(4).to_string())
    print(f"\ntop 1% cutoff: {scores['anomaly_score'].quantile(0.99):.4f}")
