"""Was Isolation Forest the right choice, or just the default one?

Three unsupervised detectors are scored on the same features and compared at the
same alert budget, which is the only fair comparison in monitoring: an analyst
team has a fixed capacity, so the question is always "given N reviews, how many
real cases do we find?"

  * Amount z-score   - the naive baseline. Flags transactions that are large
                       relative to the account's own history. If a model cannot
                       beat this, it is not earning its complexity.
  * Local Outlier    - density-based. Finds points in sparse neighbourhoods
    Factor             rather than points that are easy to isolate.
  * Isolation Forest - what the pipeline ships.

Run: python src/model_comparison.py
"""
import json

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler

import config
from ml_layer import build_features, RANDOM_STATE

BUDGET = 228  # the shipped alert volume


def _recall_at_budget(score: np.ndarray, labels: pd.Series, budget: int = BUDGET) -> dict:
    """How many known cases land in the top `budget` most anomalous."""
    order = np.argsort(-score)
    caught = int(labels.to_numpy()[order][:budget].sum())
    total = int(labels.sum())
    return {
        "cases_caught": caught,
        "of": total,
        "recall": round(caught / total, 4),
        "precision": round(caught / budget, 4),
    }


def run():
    df = pd.read_csv(config.CLEAN_TRANSACTIONS, parse_dates=["timestamp"])
    truth = (pd.read_csv(config.GROUND_TRUTH).drop_duplicates("transaction_id")
             .set_index("transaction_id")["is_laundering_pattern"])
    labels = df["transaction_id"].map(truth).fillna(0).astype(int)

    X = build_features(df)
    Xs = StandardScaler().fit_transform(X)
    results = {}

    # 1. Naive baseline: how large is this amount for this account?
    results["amount z-score (baseline)"] = _recall_at_budget(
        X["amount_z_vs_account"].to_numpy(), labels)

    # 2. Local Outlier Factor, density based.
    lof = LocalOutlierFactor(n_neighbors=35, contamination=0.02, n_jobs=-1)
    lof.fit_predict(Xs)
    results["Local Outlier Factor"] = _recall_at_budget(
        -lof.negative_outlier_factor_, labels)

    # 3. Isolation Forest, what ships.
    iso = IsolationForest(n_estimators=300, contamination=0.02,
                          max_samples=min(4096, len(X)),
                          random_state=RANDOM_STATE, n_jobs=-1).fit(Xs)
    results["Isolation Forest (shipped)"] = _recall_at_budget(
        -iso.score_samples(Xs), labels)

    out = pd.DataFrame(results).T
    print(f"\nUnsupervised detectors at a {BUDGET}-alert budget\n")
    print(out.to_string())

    path = config.OUTPUTS / "model_comparison.json"
    path.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {path.name}")
    return results


if __name__ == "__main__":
    run()
