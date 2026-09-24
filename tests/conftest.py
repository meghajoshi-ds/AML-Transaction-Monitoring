"""Shared fixtures: builders for small, hand-checkable transaction frames."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

BASE = pd.Timestamp("2025-06-01 09:00:00")


def txn(sender="ACC1", receiver="ACC2", amount=100.0, offset_hours=0.0,
        sender_country="United Kingdom", receiver_country="United Kingdom"):
    """One transaction, positioned relative to a fixed base time."""
    return {
        "transaction_id": None,
        "timestamp": BASE + pd.Timedelta(hours=offset_hours),
        "sender_account": sender,
        "receiver_account": receiver,
        "amount": amount,
        "sender_country": sender_country,
        "receiver_country": receiver_country,
        "transaction_type": "transfer",
        "channel": "online_transfer",
    }


@pytest.fixture
def frame():
    """Build a cleaned-shape frame from txn() dicts, indexed 0..n-1."""
    def _build(rows):
        df = pd.DataFrame(rows)
        df["transaction_id"] = [f"T{i:03d}" for i in range(len(df))]
        return df.sort_values("timestamp").reset_index(drop=True)
    return _build
