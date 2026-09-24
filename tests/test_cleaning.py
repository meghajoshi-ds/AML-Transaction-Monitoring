"""Tests for the cleaning layer.

Timestamp parsing and de-duplication are tested together because the order of
those two operations is load-bearing: one replay pair in the real file is only
detectable as a duplicate after both formats have been parsed.
"""
import pandas as pd
import pytest

import cleaning


# --------------------------------------------------------------------------
# parse_timestamps
# --------------------------------------------------------------------------

def test_parses_both_formats_in_one_column():
    s = pd.Series(["2025-03-08 10:40:21", "30/04/2025 00:13"])
    out = cleaning.parse_timestamps(s)
    assert out.iloc[0] == pd.Timestamp("2025-03-08 10:40:21")
    assert out.iloc[1] == pd.Timestamp("2025-04-30 00:13:00")


def test_slash_format_is_read_day_first_not_month_first():
    # The bug this guards against: 03/04/2025 read as 4 March instead of
    # 3 April. Ambiguous dates are exactly the ones inference gets wrong, and
    # it fails silently - no error, just a transaction in the wrong month.
    out = cleaning.parse_timestamps(pd.Series(["03/04/2025 09:00"]))
    assert out.iloc[0] == pd.Timestamp("2025-04-03 09:00:00")
    assert out.iloc[0].month == 4


def test_unparseable_timestamp_becomes_nat_rather_than_raising():
    out = cleaning.parse_timestamps(pd.Series(["not a date"]))
    assert pd.isna(out.iloc[0])


# --------------------------------------------------------------------------
# standardise_country
# --------------------------------------------------------------------------

@pytest.mark.parametrize("variant", ["US", "USA", "U.S.A.", "united states",
                                     "United States", " united states "])
def test_us_variants_fold_to_one_name(variant):
    assert cleaning.standardise_country(pd.Series([variant])).iloc[0] == "United States"


@pytest.mark.parametrize("variant", ["UK", "U.K.", "uk", "United kingdom",
                                     "United Kingdom"])
def test_uk_variants_fold_to_one_name(variant):
    assert cleaning.standardise_country(pd.Series([variant])).iloc[0] == "United Kingdom"


def test_unmapped_countries_pass_through_untouched():
    out = cleaning.standardise_country(pd.Series(["Spain", "Seychelles"]))
    assert list(out) == ["Spain", "Seychelles"]


def test_missing_country_stays_missing_rather_than_becoming_a_string():
    # It must stay NA so the customer-file imputation can find and fill it.
    assert pd.isna(cleaning.standardise_country(pd.Series([None])).iloc[0])


# --------------------------------------------------------------------------
# clean() - end to end on the real file
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cleaned():
    return cleaning.clean(verbose=False)


def test_every_timestamp_parses(cleaned):
    df, _, log = cleaned
    assert log["unparsed_timestamps"] == 0
    assert df["timestamp"].notna().all()


def test_all_replays_are_removed(cleaned):
    df, _, log = cleaned
    assert log["exact_duplicates_dropped"] == 14
    # The pair that differs only in seconds precision - the reason de-duplication
    # has to run after timestamp parsing, not before.
    assert log["near_duplicates_dropped"] == 1
    assert not df["transaction_id"].duplicated().any()


def test_unscoreable_amounts_are_quarantined_not_deleted(cleaned):
    df, quarantine, log = cleaned
    assert len(quarantine) == 80
    assert set(quarantine["quarantine_reason"]) == {"amount_missing", "amount_negative"}
    assert (df["amount"] > 0).all(), "no missing or negative amounts survive into detection"


def test_no_country_variants_survive(cleaned):
    df, _, _ = cleaned
    countries = set(df["sender_country"]) | set(df["receiver_country"])
    assert not {"US", "USA", "U.S.A.", "united states", "UK", "uk", "U.K."} & countries
    assert df["sender_country"].notna().all(), "imputed from the customer file"


def test_large_amounts_are_kept_uncapped(cleaned):
    # In AML a large unexplained transfer is the signal, not an outlier to trim.
    df, _, _ = cleaned
    assert df["amount"].max() > 300_000


def test_leaky_transaction_type_is_neutralised(cleaned):
    # 'wire_transfer' as a transaction_type marks precisely the 39 injected
    # rapid-movement rows; as a one-hot feature it is a perfect giveaway.
    df, _, log = cleaned
    assert log["wire_transfer_type_remapped"] == 39
    assert "wire_transfer" not in set(df["transaction_type"])
    assert "wire_transfer" in set(df["channel"]), "still valid as a channel"
