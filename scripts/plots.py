import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SHARES = [20, 30, 50]
GRAY = "#8a8985"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e6e5e1"

# one color, line style and marker per router, the same in every figure
ROUTERS = {
    "a lr plus_agree_k1": ("Router A (1 try)", "#2a78d6", "-", "o"),
    "b gb plus_answer": ("Router B (0 tries)", "#eb6834", "-", "s"),
    "agreement rule": ("Agreement rule (5 tries)", "#1baf7a", "--", "^"),
    "difficulty": ("Difficulty label", "#eda100", "-.", "D"),
    "crash rule": ("Crash rule", "#e87ba4", ":", "v"),
    "a lr plus_agree_k5": ("A with 5 tries", "#008300", "--", "P"),
}
REFERENCE = {
    "random": ("Random", GRAY, (0, (1, 2))),
    "oracle": ("Oracle (perfect)", GRAY, (0, (5, 3))),
}


# thin recessive axes and grid, sized for a one-column report page
def style():
    plt.rcParams.update({
        "font.size": 9,
        "axes.edgecolor": INK_2,
        "axes.labelcolor": INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "xtick.color": INK_2,
        "ytick.color": INK_2,
        "legend.frameon": False,
        "lines.linewidth": 1.6,
        "savefig.bbox": "tight",
    })


def save(fig, out, name):
    for ext in ["pdf", "png"]:
        fig.savefig(out / f"{name}.{ext}", dpi=200)
    plt.close(fig)
    print(f"saved {out / name}.pdf and .png")


# mean curve per router (the rehearsal has 3 seeds per classifier)
def mean_curves(path):
    df = pd.read_csv(path)
    return df.groupby(["router", "escalated"], as_index=False)[["share", "ex"]].mean()


# a horizontal reference line, labelled just outside the right edge
def ref_line(ax, y, label):
    ax.axhline(y, color=GRAY, linewidth=0.8, zorder=1)
    ax.text(101.5, y, label, color=INK_2, ha="left", va="center", fontsize=8, clip_on=False)


# accuracy against share sent to the 32B, every router on one set of axes
def routing(curves, small, large, title, out, name, check=None):
    fig, ax = plt.subplots(figsize=(6.5, 4.4))
    for key, (label, color, ls) in REFERENCE.items():
        c = curves[curves["router"] == key]
        ax.plot(100 * c["share"], c["ex"], color=color, linestyle=ls, linewidth=1.1, label=label, zorder=2)

    for key, (label, color, ls, marker) in ROUTERS.items():
        c = curves[curves["router"] == key]
        if c.empty or key == "a lr plus_agree_k5":
            continue
        
        ax.plot(100 * c["share"], c["ex"], color=color, linestyle=ls, label=label, zorder=3)
        n = c["escalated"].max()
        pts = c[c["escalated"].isin([round(s / 100 * n) for s in SHARES])]
        ax.plot(100 * pts["share"], pts["ex"], linestyle="none", marker=marker, markersize=6, color=color, markeredgecolor="white", markeredgewidth=1, zorder=4)
        
        if check is not None and key in check.index:
            for s, (_, p) in zip(SHARES, pts.iterrows()):
                assert abs(p["ex"] - check.loc[key, f"ex_{s}"]) < 0.01, f"{key} at {s}% doesn't match the router table"

    ref_line(ax, small, f"Always-small\n(7B) {small:.1f}")
    ref_line(ax, large, f"Always-large\n(32B) {large:.1f}")
    for s in SHARES:
        ax.axvline(s, color=GRID, linewidth=1.2, zorder=0)

    ax.set_xlim(0, 100)
    ax.set_xlabel("Questions sent to the 32B (%)")
    ax.set_ylabel("Execution accuracy, EX (%)")
    ax.set_title(title, loc="left", fontsize=10, color=INK)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), fontsize=8, ncol=4)
    save(fig, out, name)


# ROC-AUC against the number of extra tries, for the frozen classifier types
def tries_auc(results, out):
    df = pd.read_csv(results)
    steps = ["plus_answer"] + [f"plus_agree_k{k}" for k in range(1, 6)]
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    
    for target, model, key in [("a", "lr", "a lr plus_agree_k1"), ("b", "gb", "b gb plus_answer")]:
        rows = df[(df["target"] == target) & (df["model"] == model)].set_index("features").loc[steps]
        label = {
            "a": "A: is the 7B wrong? (logistic regression)", 
            "b": "B: worth sending up? (gradient boosting)"
        }[target]
        
        _, color, _, marker = ROUTERS[key]
        ax.errorbar(range(6), rows["roc_auc_mean"], yerr=rows["roc_auc_std"], color=color, marker=marker,
            markersize=6, markeredgecolor="white", capsize=3, label=label)

    ax.set_xticks(range(6))
    ax.set_xlabel("Extra tries the 7B makes (0 = its answer only)")
    ax.set_ylabel("ROC-AUC (5-fold, 3 seeds)")
    ax.set_ylim(0.70, 0.90)
    ax.set_title("How well each classifier spots the 7B's mistakes, by number of tries (training)", loc="left", fontsize=10, color=INK)
    ax.legend(loc="lower right", fontsize=8)
    save(fig, out, "e3_tries_auc")


# accuracy against seconds and against dollars per question, side by side
def cost(curves, points, out):
    df = pd.read_csv(curves)
    pts = pd.read_csv(points).set_index(["router", "point"])
    small = pts.loc[("always small", "0%")]
    large = pts.loc[("always large", "100%")]
    keys = ["b gb plus_answer", "a lr plus_agree_k1", "agreement rule", "a lr plus_agree_k5"]

    fig, axes = plt.subplots(1, 2, figsize=(6.5, 3.4), sharey=True)
    for ax, col, xlabel, ha in [(axes[0], "seconds_together", "Seconds per question (tries sent together)", "left"), (axes[1], "usd_per_1000", "Dollars per 1,000 questions (32B paid)", "right")]:
        c = df[df["router"] == "random"]
        ax.plot(c[col], c["ex"], color=GRAY, linestyle=REFERENCE["random"][2], linewidth=1.1, label="Random")
        for key in keys:
            label, color, ls, _ = ROUTERS[key]
            c = df[df["router"] == key]
            ax.plot(c[col], c["ex"], color=color, linestyle=ls, label=label)

        for p in [small, large]:
            ax.plot(p[col], p["ex"], marker="o", markersize=7, color=INK, markeredgecolor="white", linestyle="none", zorder=5)
            
        ax.annotate("Always-small", (small[col], small["ex"]), xytext=(4, -11), textcoords="offset points", ha="left", fontsize=8, color=INK)
        ax.axvline(large[col], color=GRAY, linewidth=0.8, zorder=1)
        ax.text(large[col], 60.1, " Always-large " if ha == "left" else "Always-large ", ha=ha, va="top", fontsize=8, color=INK)
        ax.set_xlabel(xlabel)
        ax.set_xlim(left=0)
        ax.set_ylim(48.6, 60.2)

    axes[0].set_ylabel("Execution accuracy, EX (%)")
    axes[0].set_title("Time and money against accuracy (test)", loc="left", fontsize=10, color=INK)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, -0.02), fontsize=8, ncol=5, frameon=False)
    save(fig, out, "e5_cost")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outputs", default="outputs", help="folder with the result CSVs")
    ap.add_argument("--out", default="figures", help="folder for the figures")
    args = ap.parse_args()

    src = Path(args.outputs)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    style()

    routers = pd.read_csv(src / "e4_routers.csv").set_index("router")
    test = mean_curves(src / "e4_curves.csv")
    routing(test, 49.80, 57.80, "Accuracy against share sent to the 32B (500 test questions)", out, "e4_routing_test", check=routers)

    train = mean_curves(src / "rehearsal_curves.csv")
    routing(train, 54.26, 64.41, "Accuracy against share sent to the 32B (1,034 training questions, mean of 3 seeds)", out, "rehearsal_routing_train")

    tries_auc(src / "e3_results.csv", out)
    cost(src / "e5_curves.csv", src / "e5_points.csv", out)


if __name__ == "__main__":
    main()
