"""Run the whole pipeline end to end: profile -> clean -> rules -> model -> evaluate -> figures.

    python src/run_pipeline.py
"""
import json
import time

import config
import profiling
import cleaning
import evaluate
import figures


def main():
    t0 = time.time()

    print("[1/5] profiling raw data")
    profiling.profile(verbose=False)

    print("[2/5] cleaning")
    clean_df, quarantine, log = cleaning.clean(verbose=False)
    clean_df.to_csv(config.CLEAN_TRANSACTIONS, index=False)
    quarantine.to_csv(config.OUTPUTS / "quarantined_rows.csv", index=False)
    print(f"      {log['rows_in']:,} raw -> {log['rows_out']:,} clean "
          f"({log['exact_duplicates_dropped'] + log['near_duplicates_dropped']} replays, "
          f"{len(quarantine)} quarantined)")

    print("[3/5] rules + [4/5] anomaly model + evaluation")
    report = evaluate.run()

    print("[5/5] figures")
    figures.fig_fp_reduction(report)
    figures.fig_calibration(report)
    figures.fig_rule_contribution(report)
    figures.fig_detection_curve(report)
    # The evasion chart is drawn from adversarial.json rather than re-running
    # the attack, which takes ~2 minutes. Run `python src/adversarial.py` to
    # regenerate the underlying numbers.
    n_figures = 4
    if (config.OUTPUTS / "adversarial.json").exists():
        figures.fig_adversarial()
        n_figures = 5

    h = report["headline"]
    print("\n" + "=" * 62)
    print(f"  rules-only baseline : {h['baseline_alerts']:>6,} alerts   "
          f"precision {h['baseline_precision']:.1%}   recall {h['baseline_recall']:.0%}")
    print(f"  rules + anomaly     : {h['combined_alerts']:>6,} alerts   "
          f"precision {h['combined_precision']:.1%}   recall {h['combined_recall']:.0%}")
    print(f"  false positives cut : {h['false_positive_reduction_pct']}%  "
          f"({h['baseline_false_positives']:,} -> {h['combined_false_positives']})")
    print("=" * 62)
    print(f"\nwrote {config.METRICS.name}, {config.CASE_MANAGEMENT.name}, "
          f"{n_figures} figures  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
