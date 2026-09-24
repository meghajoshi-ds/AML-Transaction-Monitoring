"""Load the cleaned book into SQLite and run the queries in `sql/`.

The rules exist twice in this project: as pandas functions in `rules.py`, which
the pipeline uses, and as SQL in `sql/`, which is how the same logic would be
expressed against a bank's warehouse. `tests/test_sql.py` asserts the two agree
transaction for transaction, so the SQL is verified rather than illustrative.

SQLite is used because it ships with Python. Nothing here needs installing.
"""
import sqlite3

import pandas as pd

import config
from timeutils import epoch_ns

SQL_DIR = config.ROOT / "sql"


def build_db(df: pd.DataFrame = None) -> sqlite3.Connection:
    """In-memory database holding the cleaned transactions and the customers.

    `ts` is epoch SECONDS: SQLite window frames do arithmetic on numbers, so a
    RANGE frame of '604800 FOLLOWING' is exactly seven days.
    """
    if df is None:
        df = pd.read_csv(config.CLEAN_TRANSACTIONS, parse_dates=["timestamp"])
    con = sqlite3.connect(":memory:")

    t = df.copy()
    t["ts"] = epoch_ns(t["timestamp"]) // 1_000_000_000
    t["timestamp"] = t["timestamp"].astype(str)
    t.to_sql("transactions", con, index=False)
    pd.read_csv(config.CUSTOMERS).to_sql("customers", con, index=False)
    # Labels are loaded for 04_rule_contribution only, which is evaluation.
    # No detection query touches this table.
    (pd.read_csv(config.GROUND_TRUTH).drop_duplicates("transaction_id")
       .to_sql("labels", con, index=False))

    con.executescript("""
        CREATE INDEX idx_sender   ON transactions(sender_account, ts);
        CREATE INDEX idx_receiver ON transactions(receiver_account, ts);
        CREATE INDEX idx_amount   ON transactions(amount);
    """)
    return con


def run(name: str, con: sqlite3.Connection = None) -> pd.DataFrame:
    """Run `sql/<name>.sql` and return the result."""
    con = con or build_db()
    return pd.read_sql_query((SQL_DIR / f"{name}.sql").read_text(), con)


if __name__ == "__main__":
    con = build_db()
    for query in sorted(SQL_DIR.glob("*.sql")):
        out = run(query.stem, con)
        print(f"\n=== {query.name} ({len(out):,} rows) ===")
        print(out.head(8).to_string(index=False))
