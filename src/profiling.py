"""Step 2 - data profiling.

Looks at the raw file before anything is fixed, so every cleaning decision in
cleaning.py can point at a number here. Writes outputs/profile_report.md.
"""
import pandas as pd
import numpy as np

import config


def _section(title):
    return f"\n## {title}\n\n"


def profile(verbose: bool = True):
    df = pd.read_csv(config.RAW_TRANSACTIONS, dtype=str)
    cust = pd.read_csv(config.CUSTOMERS)
    amt = pd.to_numeric(df["amount"], errors="coerce")

    out = ["# Data profile - raw transactions\n",
           f"\n{len(df):,} rows x {df.shape[1]} columns. "
           f"Generated before any cleaning.\n"]

    # --- completeness -------------------------------------------------
    out.append(_section("Missing values"))
    miss = df.replace("", np.nan).isna().sum()
    out.append(miss[miss > 0].to_frame("missing").to_markdown() + "\n")

    # --- duplicate ids --------------------------------------------------
    out.append(_section("Duplicate transaction_id"))
    dup_ids = df["transaction_id"][df["transaction_id"].duplicated()].unique()
    dups = df[df["transaction_id"].isin(dup_ids)].sort_values("transaction_id")
    full_dupes = dups.duplicated(keep=False) & dups.duplicated(subset=list(df.columns), keep=False)
    out.append(f"- {len(dup_ids)} ids appear more than once, covering {len(dups)} rows.\n")
    out.append(f"- Rows that are identical across **all 10 columns**: {int(full_dupes.sum())}.\n")
    out.append("\nSample of the duplicated ids:\n\n")
    out.append(dups.head(10).to_markdown(index=False) + "\n")

    # --- negative + zero amounts ---------------------------------------
    out.append(_section("Negative amounts"))
    neg = df[amt < 0]
    out.append(f"- {len(neg)} rows with amount < 0, range "
               f"{amt[amt < 0].min():.2f} to {amt[amt < 0].max():.2f}.\n")
    out.append("\nTransaction types they carry:\n\n")
    out.append(neg["transaction_type"].value_counts().to_frame("rows").to_markdown() + "\n")

    # --- amount distribution -------------------------------------------
    out.append(_section("Amount distribution"))
    q = amt[amt > 0].describe(percentiles=[.5, .9, .99, .999])
    out.append(q.to_frame("amount").to_markdown() + "\n")
    out.append(f"\n- Rows above GBP 50,000: {int((amt > 50_000).sum())}\n")
    out.append(f"- Largest single amount: GBP {amt.max():,.2f}\n")

    # --- timestamps ------------------------------------------------------
    out.append(_section("Timestamp formats"))
    slash = df["timestamp"].str.contains("/", na=False)
    out.append(f"- `YYYY-MM-DD HH:MM:SS`: {int((~slash).sum()):,}\n")
    out.append(f"- `DD/MM/YYYY HH:MM`: {int(slash.sum()):,}\n")
    dayparts = df.loc[slash, "timestamp"].str.slice(0, 2).astype(int)
    out.append(f"- In the slash-format rows the first component ranges {dayparts.min()}-"
               f"{dayparts.max()}, i.e. >12 occurs, confirming day-first not month-first.\n")

    # --- country formatting ----------------------------------------------
    out.append(_section("Country value formatting"))
    vc = pd.concat([df["sender_country"], df["receiver_country"]]).value_counts(dropna=False)
    out.append(vc.to_frame("rows").to_markdown() + "\n")
    out.append(f"\nCanonical country names in the customer file: "
               f"{sorted(cust['home_country'].unique())}\n")

    # --- categorical columns ---------------------------------------------
    out.append(_section("Categorical columns"))
    for col in ["currency", "transaction_type", "channel"]:
        out.append(f"\n**{col}**\n\n")
        out.append(df[col].value_counts(dropna=False).to_frame("rows").to_markdown() + "\n")

    # --- leakage check ----------------------------------------------------
    out.append(_section("transaction_id prefix check"))
    out.append("The id column is supposed to be an opaque reference. It is not:\n\n")
    out.append(df["transaction_id"].str.slice(0, 4).value_counts()
               .to_frame("rows").to_markdown() + "\n")
    out.append("\n`TXNS`/`TXNR` are the injected structuring and rapid-movement rows. "
               "Any feature derived from the id would score perfectly and mean nothing, "
               "so the column is dropped before modelling.\n")

    # --- account level volumes --------------------------------------------
    out.append(_section("Account-level activity"))
    sent = df["sender_account"].value_counts()
    out.append(f"- Distinct sending accounts: {sent.size:,}\n")
    out.append(f"- Transactions sent per account: median {sent.median():.0f}, "
               f"p99 {sent.quantile(.99):.0f}, max {sent.max()}\n")
    accounts_in_txns = set(df["sender_account"]) | set(df["receiver_account"])
    out.append(f"- Accounts appearing in transactions but missing from the customer file: "
               f"{len(accounts_in_txns - set(cust['account_id'])):,}\n")

    config.OUTPUTS.joinpath("profile_report.md").write_text("".join(out))
    if verbose:
        print("".join(out))


if __name__ == "__main__":
    profile()
