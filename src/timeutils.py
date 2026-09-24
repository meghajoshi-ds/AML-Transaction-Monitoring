"""Datetime-unit normalisation.

pandas 2 reads timestamps as `datetime64[ns]`; pandas 3 reads them as
`datetime64[us]`. Casting a timestamp column straight to int64 therefore yields
nanoseconds on one and microseconds on the other, while `pd.Timedelta(...).value`
is always nanoseconds. Mixing the two silently makes every time window 1000x too
wide - no error, just wrong answers, which is the worst kind of bug.

Everything that does time arithmetic goes through `epoch_ns` so the unit is
pinned at one place regardless of the installed pandas.
"""
import numpy as np
import pandas as pd


def epoch_ns(values) -> np.ndarray:
    """Epoch nanoseconds as int64, whatever datetime unit the input carries."""
    return np.asarray(pd.to_datetime(values), dtype="datetime64[ns]").astype("int64")
