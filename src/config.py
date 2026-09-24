"""Shared paths and constants for the AML monitoring pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUTS = ROOT / "outputs"
FIGURES = OUTPUTS / "figures"

RAW_TRANSACTIONS = DATA / "aml_transactions_raw.csv"
CUSTOMERS = DATA / "aml_customers.csv"
GROUND_TRUTH = DATA / "aml_ground_truth_labels.csv"

CLEAN_TRANSACTIONS = OUTPUTS / "transactions_clean.csv"
ALERTS = OUTPUTS / "alerts.csv"
CASE_MANAGEMENT = OUTPUTS / "case_management.csv"
METRICS = OUTPUTS / "metrics.json"

# Cash reporting threshold the structuring rule is built around (GBP).
REPORTING_THRESHOLD = 10_000

# Offshore / secrecy jurisdictions. Chosen because they are the long tail of
# the customer book (18-34 accounts each vs ~300 for every mainstream country),
# which is what a real high-risk list looks like against a retail portfolio.
HIGH_RISK_COUNTRIES = {"Cyprus", "Malta", "Seychelles", "Panama", "Cayman Islands"}

# Canonical spellings, keyed by lowercased/stripped variant.
COUNTRY_CANON = {
    "united states": "United States", "us": "United States", "usa": "United States",
    "u.s.a.": "United States", "u.s.": "United States", "united states of america": "United States",
    "united kingdom": "United Kingdom", "uk": "United Kingdom", "u.k.": "United Kingdom",
    "great britain": "United Kingdom", "gb": "United Kingdom",
}

for _d in (OUTPUTS, FIGURES):
    _d.mkdir(parents=True, exist_ok=True)
