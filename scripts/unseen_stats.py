import argparse

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from features import load_jsonl
from route import BOOT, BOOT_SEED, MAIN_A, MAIN_B, SHARES, TIE_SEED, boot_range, outcomes, router

MAIN = {
    "A": MAIN_A, 
    "B": MAIN_B
}


# 95% range of a paired EX difference when whole databases are resampled
def cluster_range(diff, groups, boot_seed=BOOT_SEED, boot=BOOT):
    _, g = np.unique(groups, return_inverse=True)
    sums, counts = np.bincount(g, weights=diff), np.bincount(g)
    draws = np.random.default_rng(boot_seed).multinomial(len(sums), np.full(len(sums), 1 / len(sums)), size=boot)
    return np.percentile(100 * (draws @ sums) / (draws @ counts), [2.5, 97.5])


# questions whose database size is inside the range the router was trained on
def in_training_range(df, train):
    ok = np.ones(len(df), dtype=bool)
    for col in ["db_tables", "db_columns"]:
        ok &= df[col].between(train[col].min(), train[col].max()).to_numpy()

    return ok


# one result row: router vs random at one share, with a 95% range
def row(analysis, name, share, x, y, low, high):
    return {
        "analysis": analysis, "router": name, "share": share,
        "ex": round(100 * x.mean(), 2), "ex_random": round(100 * y.mean(), 2),
        "diff": round(100 * (x - y).mean(), 2), "ci_low": round(float(low), 2), "ci_high": round(float(high), 2),
        "includes_zero": bool(low <= 0 <= high),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default="outputs/features_train.csv", help="the training feature table")
    ap.add_argument("--test_features", required=True, help="the feature table of the routed questions")
    ap.add_argument("--scores", required=True, help="the _scores.csv written by route.py --mode final")
    ap.add_argument("--runs", required=True, help="start of the run file names of the routed questions")
    ap.add_argument("--out", required=True, help="CSV to write")
    args = ap.parse_args()

    train, df, scores = pd.read_csv(args.features), pd.read_csv(args.test_features), pd.read_csv(args.scores)
    n = len(df)
    
    assert (scores["question_id"] == df["question_id"]).all(), "scores and features don't match"
    small = np.array([r["samples"][0]["correct"] for r in load_jsonl(f"{args.runs}_qwen7b_check.jsonl")])
    large = np.array([r["samples"][0]["correct"] for r in load_jsonl(f"{args.runs}_qwen32b_check.jsonl")])
    assert (small == 1 - df["label_a"]).all(), "labels don't match the checks"

    print("how well the risk scores rank the questions: ROC-AUC / PR-AUC")
    for label in ["label_a", "label_b"]:
        y = df[label].to_numpy()
        cells = {name: scores[full] for name, full in MAIN.items()}
        cells["agreement alone"] = -df["agree_k5"]
        print(f"  {label} (base rate {y.mean():.3f}): " + ", ".join(f"{name} {roc_auc_score(y, s):.3f} / {average_precision_score(y, s):.3f}" for name, s in cells.items()))

    tiebreak = np.random.default_rng(TIE_SEED).permutation(n)
    rows = []
    analyses = [("all questions", np.ones(n, dtype=bool)), ("databases in training range", in_training_range(df, train))]
    for analysis, mask in analyses:
        k = int(mask.sum())
        print(f"\n{analysis}: {k} questions on {df['db_id'][mask].nunique()} databases, always small {100 * small[mask].mean():.2f}, always large {100 * large[mask].mean():.2f}")
        groups = df["db_id"].to_numpy()[mask]
        boot = np.random.default_rng(BOOT_SEED).multinomial(k, np.full(k, 1 / k), size=BOOT)
        rand = router(small[mask], None, tiebreak[mask])
        
        for name, full in MAIN.items():
            r = router(small[mask], [(scores[full].to_numpy()[mask], np.zeros(k, dtype=int))], tiebreak[mask])
            
            for s in SHARES:
                m = round(s * k)
                x, y = outcomes(r, large[mask], m)[0], outcomes(rand, large[mask], m)[0]
                tests = [("questions resampled", boot_range(x - y, boot))]
                if analysis == "all questions":
                    tests.append(("databases resampled", cluster_range(x - y, groups)))
                    
                for kind, (low, high) in tests:
                    rows.append(row(f"{analysis}, {kind}", name, f"{s:.0%}", x, y, low, high))
                    print(f"{name} vs random at {s:.0%} ({kind}): {rows[-1]['ex']:.2f} vs {rows[-1]['ex_random']:.2f}, {rows[-1]['diff']:+.2f} [{low:+.2f}, {high:+.2f}]")

    pd.DataFrame(rows).to_csv(args.out, index=False)
    print(f"\nsaved {args.out}")


if __name__ == "__main__":
    main()
