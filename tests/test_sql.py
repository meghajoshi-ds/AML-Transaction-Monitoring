"""The SQL rules must agree with the pandas rules, transaction for transaction.

The same logic exists twice in this project: as pandas functions the pipeline
runs, and as SQL in `sql/` showing how it would be expressed against a
warehouse. Two implementations that drift are worse than one, so these tests
pin them together. They are the reason the SQL can be called verified rather
than illustrative.
"""
import pandas as pd
import pytest

import cleaning
import rules
import sql_runner


@pytest.fixture(scope="module")
def book():
    """Cleaned transactions, built from the raw file rather than read from disk.

    The pipeline writes outputs/transactions_clean.csv, but that file is
    gitignored as a regenerable intermediate, so it does not exist on a fresh
    checkout. Deriving it here keeps the suite self-contained: tests should not
    depend on another command having been run first.
    """
    clean, _quarantine, _log = cleaning.clean(verbose=False)
    return clean


@pytest.fixture(scope="module")
def con(book):
    return sql_runner.build_db(book)


def _python_ids(book, rule_fn):
    return set(book.loc[rule_fn(book), "transaction_id"])


def _sql_ids(name, con):
    return set(sql_runner.run(name, con)["transaction_id"])


def test_structuring_sql_matches_python(book, con):
    sql, py = _sql_ids("01_structuring", con), _python_ids(book, rules.rule_structuring)
    assert sql == py, (f"SQL-only: {sorted(sql - py)[:5]}, "
                       f"Python-only: {sorted(py - sql)[:5]}")


def test_rapid_movement_sql_matches_python(book, con):
    sql = _sql_ids("02_rapid_movement", con)
    py = _python_ids(book, rules.rule_rapid_movement)
    assert sql == py, (f"SQL-only: {sorted(sql - py)[:5]}, "
                       f"Python-only: {sorted(py - sql)[:5]}")


def test_high_risk_country_sql_matches_python(book, con):
    sql = _sql_ids("03_high_risk_country", con)
    py = _python_ids(book, rules.rule_high_risk_country)
    assert sql == py


def test_rule_contribution_reproduces_the_headline_finding(con):
    """The project's central result, computed independently in SQL."""
    out = sql_runner.run("04_rule_contribution", con).set_index("rule")

    # The targeted typologies each find cases nothing else finds.
    assert out.loc["structuring", "cases_no_other_rule_found"] > 0
    assert out.loc["rapid_movement", "cases_no_other_rule_found"] > 0

    # The broad screens raise thousands of alerts and find nothing unique.
    assert out.loc["high_risk_country", "alerts_only_this_rule"] > 5_000
    assert out.loc["high_risk_country", "cases_no_other_rule_found"] == 0
    assert out.loc["round_amount", "cases_no_other_rule_found"] == 0


def test_every_detection_query_avoids_the_labels():
    """Detection must not read ground truth. Only the evaluation query may."""
    for path in sorted(sql_runner.SQL_DIR.glob("*.sql")):
        body = path.read_text().lower()
        if path.stem == "04_rule_contribution":
            assert "labels" in body, "the evaluation query should use them"
        else:
            assert "labels" not in body, f"{path.name} reads the labels"
