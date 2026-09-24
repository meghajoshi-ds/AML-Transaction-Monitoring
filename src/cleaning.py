"""Step 3 - cleaning.

Every decision here is recorded in DECISIONS.md with the profile number that
drove it. Returns a clean frame plus a quarantine frame of rows that cannot be
scored, so nothing is silently dropped.
"""
import numpy as np
import pandas as pd

import config


def standardise_country(s: pd.Series) -> pd.Series:
    """Fold spelling variants ('USA', 'u.k.', 'United kingdom') onto one name."""
    key = s.astype("string").str.strip().str.lower()
    return key.map(config.COUNTRY_CANON).fillna(s.astype("string").str.strip())


def parse_timestamps(s: pd.Series) -> pd.Series:
    """Parse the two formats present without letting either reinterpret the other.

    Rows containing '/' are DD/MM/YYYY HH:MM (confirmed in profiling: the first
    component exceeds 12), everything else is ISO. Parsing them separately
    avoids pandas silently reading 03/04/2025 as 4 March.
    """
    s = s.astype("string").str.strip()
    is_slash = s.str.contains("/", na=False)
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    out.loc[~is_slash] = pd.to_datetime(s[~is_slash], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    out.loc[is_slash] = pd.to_datetime(s[is_slash], format="%d/%m/%Y %H:%M", errors="coerce")
    return out


def clean(verbose: bool = True):
    df = pd.read_csv(config.RAW_TRANSACTIONS)
    cust = pd.read_csv(config.CUSTOMERS)
    log = {"rows_in": len(df)}

    # 1. Timestamps -> one dtype. Done FIRST because de-duplication depends on it:
    #    one replay pair differs only in timestamp formatting.
    df["timestamp"] = parse_timestamps(df["timestamp"])
    log["unparsed_timestamps"] = int(df["timestamp"].isna().sum())

    # 2. Country names -> canonical spelling.
    for col in ("sender_country", "receiver_country"):
        df[col] = standardise_country(df[col])

    # 3. Impute missing sender_country from the customer file. Justified by the
    #    profile: where sender_country is present it equals the sending account's
    #    home_country 99.8% of the time.
    home = cust.set_index("account_id")["home_country"]
    missing_country = df["sender_country"].isna()
    df.loc[missing_country, "sender_country"] = df.loc[missing_country, "sender_account"].map(home)
    log["sender_country_imputed"] = int(missing_country.sum())

    # 4. Missing channel becomes its own level. 'unknown' is information (a feed
    #    that failed to populate), not something to guess at.
    log["channel_unknown"] = int(df["channel"].isna().sum())
    df["channel"] = df["channel"].fillna("unknown")

    # 5. De-duplicate replays, now that timestamps are comparable.
    #    Pass A: byte-identical rows.
    before = len(df)
    df = df.drop_duplicates(subset=list(df.columns), keep="first").reset_index(drop=True)
    log["exact_duplicates_dropped"] = before - len(df)

    #    Pass B: same economic event recorded at two precisions. One replay pair
    #    survives pass A because the DD/MM feed carries no seconds
    #    (06:30:52 vs 06:30:00). Match on the business key - same counterparties,
    #    same amount, same minute - and keep the higher-precision row.
    before = len(df)
    df["_minute"] = df["timestamp"].dt.floor("min")
    df["_has_seconds"] = df["timestamp"].dt.second.ne(0).astype(int)
    df = (df.sort_values("_has_seconds", ascending=False)
            .drop_duplicates(subset=["sender_account", "receiver_account", "amount",
                                     "transaction_type", "_minute"], keep="first")
            .drop(columns=["_minute", "_has_seconds"])
            .reset_index(drop=True))
    log["near_duplicates_dropped"] = before - len(df)
    log["ids_still_duplicated"] = int(df["transaction_id"].duplicated().sum())

    # 6. Leakage control. The id prefix (TXNS/TXNR) and the 39-row
    #    transaction_type 'wire_transfer' both identify injected rows exactly.
    #    The id is kept only as a reference key, never as a feature; the stray
    #    type is folded into 'transfer', which is what it actually is.
    log["wire_transfer_type_remapped"] = int((df["transaction_type"] == "wire_transfer").sum())
    df["transaction_type"] = df["transaction_type"].replace({"wire_transfer": "transfer"})

    # 7. Quarantine rows that cannot be scored rather than deleting them.
    unscoreable = df["amount"].isna() | (df["amount"] < 0)
    quarantine = df[unscoreable].copy()
    quarantine["quarantine_reason"] = np.where(
        quarantine["amount"].isna(), "amount_missing", "amount_negative")
    df = df[~unscoreable].reset_index(drop=True)
    log["quarantined_missing_amount"] = int((quarantine["quarantine_reason"] == "amount_missing").sum())
    log["quarantined_negative_amount"] = int((quarantine["quarantine_reason"] == "amount_negative").sum())

    # 8. Outliers are kept uncapped - see DECISIONS.md. Large amounts are the
    #    signal in AML, so winsorising would delete the thing being looked for.
    log["amount_over_50k_kept"] = int((df["amount"] > 50_000).sum())

    # Derived fields used by the rules and the model.
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["is_cross_border"] = (df["sender_country"] != df["receiver_country"]).astype(int)
    df["hour"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["date"] = df["timestamp"].dt.date
    log["rows_out"] = len(df)

    if verbose:
        for k, v in log.items():
            print(f"{k:32s} {v:,}")
    return df, quarantine, log


if __name__ == "__main__":
    clean_df, quarantine, log = clean()
    clean_df.to_csv(config.CLEAN_TRANSACTIONS, index=False)
    quarantine.to_csv(config.OUTPUTS / "quarantined_rows.csv", index=False)
    print(f"\nwrote {config.CLEAN_TRANSACTIONS.name} ({len(clean_df):,} rows) "
          f"and quarantined_rows.csv ({len(quarantine)} rows)")
