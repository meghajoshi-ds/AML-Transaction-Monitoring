"""Charts for the write-up.

Colours are slots 1-3 of the validated reference categorical palette, used
unchanged (blue / orange / aqua). Two series always carry a legend; values are
labelled directly rather than left to the reader to measure off an axis.
"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import config

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e3e2dc"
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE, "text.color": INK,
    "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "axes.edgecolor": GRID, "grid.color": GRID, "font.size": 10,
    "axes.titlesize": 12, "axes.titleweight": "bold", "figure.dpi": 150,
})


def _clean(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", lw=0.6, alpha=0.7)
    ax.set_axisbelow(True)


def fig_fp_reduction(m):
    base, comb = m["rules_combined_baseline"], m["combined_final"]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    labels = ["Rules only\n(baseline)", "Rules + anomaly\n(combined)"]
    tp = [base["true_positives"], comb["true_positives"]]
    fp = [base["false_positives"], comb["false_positives"]]

    ax.bar(labels, fp, color=S2, label="False positives", width=0.5,
           edgecolor=SURFACE, linewidth=2)
    ax.bar(labels, tp, bottom=fp, color=S1, label="Known laundering cases",
           width=0.5, edgecolor=SURFACE, linewidth=2)
    ax.set_ylim(0, (tp[0] + fp[0]) * 1.26)
    for x, (t, f) in enumerate(zip(tp, fp)):
        ax.text(x, t + f + (tp[0] + fp[0]) * 0.035, f"{t + f:,} alerts",
                ha="center", fontweight="bold")
        ax.text(x, t + f + (tp[0] + fp[0]) * 0.105,
                f"{f:,} false positives\n{t} cases caught",
                ha="center", fontsize=9, color=INK_2, linespacing=1.4)
    ax.set_ylabel("Alerts raised")
    ax.set_title(f"False positives cut {m['headline']['false_positive_reduction_pct']}% "
                 f"with no loss of detection", pad=14)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2)
    _clean(ax)
    fig.tight_layout()
    fig.savefig(config.FIGURES / "fp_reduction.png")
    plt.close(fig)


def fig_calibration(m):
    sweep = pd.DataFrame(m["calibration_sweep"])
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.plot(sweep["tier_b_threshold_pct"] * 100, sweep["alerts"],
            color=S1, lw=2, marker="o", ms=8, mfc=SURFACE, mew=2)
    for _, r in sweep.iterrows():
        if r["tier_b_threshold_pct"] in (0.50, 0.90, 0.99):
            ax.annotate(f"{int(r['alerts']):,}",
                        (r["tier_b_threshold_pct"] * 100, r["alerts"]),
                        textcoords="offset points", xytext=(0, 12),
                        ha="center", fontsize=9, color=INK)
    ax.axhline(m["rules_combined_baseline"]["alerts"], color=S2, lw=2, ls="--")
    ax.text(50, m["rules_combined_baseline"]["alerts"] * 0.93,
            f"rules-only baseline: {m['rules_combined_baseline']['alerts']:,} alerts",
            color=S2, fontsize=9)
    ax.axvline(m["chosen_tier_b_threshold_pct"] * 100, color=INK_2, lw=1, ls=":")
    ax.set_xlabel("Anomaly percentile a broad-screen alert must clear to escalate")
    ax.set_ylabel("Alerts sent to analysts")
    ax.set_title("Every point on this curve still catches all 139 known cases")
    _clean(ax)
    fig.tight_layout()
    fig.savefig(config.FIGURES / "calibration_curve.png")
    plt.close(fig)


def fig_rule_contribution(m):
    names = list(m["rules_individually"])
    pretty = [n.replace("_", " ") for n in names]
    alerts = [m["rules_individually"][n]["alerts"] for n in names]
    unique = [m["unique_contribution"][n]["known_cases_found_by_no_other_rule"] for n in names]

    fig, axes = plt.subplots(1, 2, figsize=(9.5, 4.0))
    axes[0].barh(pretty, alerts, color=S2, height=0.55)
    axes[0].set_title("Alerts raised (log scale)", loc="left")
    axes[0].set_xscale("log")
    for i, v in enumerate(alerts):
        axes[0].text(v * 1.15, i, f"{v:,}", va="center", fontsize=9, color=INK_2)
    axes[0].set_xlim(1, max(alerts) * 6)

    axes[1].barh(pretty, unique, color=S1, height=0.55)
    axes[1].set_title("Known cases found by no other rule", loc="left")
    for i, v in enumerate(unique):
        axes[1].text(v + 2, i, str(v), va="center", fontsize=9, color=INK_2)
    axes[1].set_xlim(0, max(unique) * 1.25)
    axes[1].set_yticklabels([])

    for ax in axes:
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.grid(axis="x", lw=0.6, alpha=0.7)
        ax.set_axisbelow(True)
        ax.invert_yaxis()
    fig.suptitle("Two rules carry the detection; one carries the alert volume",
                 fontweight="bold", x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(config.FIGURES / "rule_contribution.png")
    plt.close(fig)


def fig_detection_curve(m):
    """How many known cases you catch for a given analyst budget.

    The anomaly score alone is a decent ranker, but at any realistic review
    budget it leaves cases on the table; the rules find the last ones.
    """
    df = pd.read_csv(config.OUTPUTS / "transactions_scored.csv")
    ranked = df.sort_values("anomaly_score", ascending=False)
    caught = ranked["label"].cumsum().to_numpy()
    budget = range(1, len(ranked) + 1)

    comb, base = m["combined_final"], m["rules_combined_baseline"]
    fig, ax = plt.subplots(figsize=(7, 4.4))
    ax.plot(budget, caught, color=S3, lw=2, label="Anomaly score alone (ranked)")
    ax.scatter([comb["alerts"]], [comb["true_positives"]], s=90, color=S1,
               zorder=5, edgecolor=SURFACE, linewidth=2, label="Rules + anomaly (combined)")
    ax.scatter([base["alerts"]], [base["true_positives"]], s=90, color=S2,
               zorder=5, edgecolor=SURFACE, linewidth=2, label="Rules only (baseline)")
    ax.annotate(f"{comb['alerts']} alerts\nall {comb['true_positives']} cases",
                (comb["alerts"], comb["true_positives"]), textcoords="offset points",
                xytext=(-8, -42), fontsize=9, color=INK, ha="right")
    ax.annotate(f"{base['alerts']:,} alerts\nall {base['true_positives']} cases",
                (base["alerts"], base["true_positives"]), textcoords="offset points",
                xytext=(12, -42), fontsize=9, color=INK, ha="left")
    ax.set_xscale("log")
    ax.set_xlabel("Alerts an analyst must review (log scale)")
    ax.set_ylabel("Known laundering cases caught")
    ax.set_title("The combination beats either layer on its own", pad=10)
    ax.legend(frameon=False, loc="upper left", fontsize=9)
    _clean(ax)
    fig.tight_layout()
    fig.savefig(config.FIGURES / "detection_curve.png")
    plt.close(fig)


def fig_adversarial():
    """How each layer decays as the launderer adapts.

    Three series, so a legend is always present and every bar is direct-labelled
    - the comparison between layers is the whole point of the chart.
    """
    import json as _json
    data = _json.loads((config.OUTPUTS / "adversarial.json").read_text())
    data = list(reversed(data))
    names = [d["scenario"] for d in data]
    total = data[0]["known_cases"]
    series = [("Rules only", "rules_recall", S2),
              ("Rules + anomaly (shipped)", "shipped_recall", S1),
              ("Anomaly score alone", "ml_alone_recall", S3)]

    fig, ax = plt.subplots(figsize=(9.5, 6.2))
    h = 0.26
    ypos = range(len(names))
    for i, (label, key, colour) in enumerate(series):
        offsets = [y + (i - 1) * h for y in ypos]
        vals = [d[key] * total for d in data]
        ax.barh(offsets, vals, height=h, color=colour, label=label,
                edgecolor=SURFACE, linewidth=1.2)
        for y, v in zip(offsets, vals):
            ax.text(v + 1.5, y, f"{int(round(v))}", va="center", fontsize=8.5,
                    color=INK_2)

    ax.set_yticks(list(ypos))
    ax.set_yticklabels(names, fontsize=9.5)
    ax.set_xlabel(f"Known laundering cases caught (of {total})")
    ax.set_xlim(0, total * 1.12)
    ax.axvline(total, color=GRID, lw=1, ls="--", zorder=0)
    ax.set_title("Rules collapse when the launderer adapts; the model degrades",
                 pad=12)
    ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5, -0.19), ncol=3,
              fontsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="x", lw=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(config.FIGURES / "adversarial_decay.png")
    plt.close(fig)


if __name__ == "__main__":
    m = json.loads(config.METRICS.read_text())
    fig_fp_reduction(m)
    fig_calibration(m)
    fig_rule_contribution(m)
    fig_detection_curve(m)
    if (config.OUTPUTS / "adversarial.json").exists():
        fig_adversarial()
    print("wrote:", *[p.name for p in sorted(config.FIGURES.glob("*.png"))])
