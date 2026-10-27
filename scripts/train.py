import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, precision_recall_curve, roc_auc_score
from sklearn.model_selection import GridSearchCV, LeaveOneGroupOut, StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from features import GROUPS

TARGETS = {"a": "label_a", "b": "label_b"}
MODELS = ["lr", "rf", "gb"]
SHARES = [0.2, 0.3, 0.5]
NOT_FEATURES = {"idx", "question_id", "db_id", "difficulty", "label_a", "label_b"}

# everything the 7B's own answer gives, before any extra samples
BASE = [
    *GROUPS["question"], *GROUPS["schema"],
    *GROUPS["sql"], *GROUPS["confidence"]
]


# E2 uses every feature with all 5 samples; E3 adds groups one step at a time
def feature_sets(exp, db_columns):
    if exp == "e2":
        return {"all_k5": BASE + GROUPS["agreement_k5"]}

    return {
        "before_generation": GROUPS["question"] + GROUPS["schema"],
        "plus_answer": BASE,
        **{f"plus_agree_k{k}": BASE + GROUPS[f"agreement_k{k}"] for k in range(1, 6)},
        "plus_agree_k5_db": BASE + GROUPS["agreement_k5"] + db_columns,
    }


# one classifier with class weights, plus a small grid of settings to pick from
def model(name, seed):
    if name == "lr":
        est = make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=5000))
        grid = {"logisticregression__C": [0.01, 0.1, 1, 10]}

    elif name == "rf":
        est = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=seed)
        grid = {"max_depth": [6, None], "min_samples_leaf": [1, 10]}

    else:
        est = HistGradientBoostingClassifier(learning_rate=0.05, class_weight="balanced", random_state=seed)
        grid = {"max_depth": [2, 4], "max_iter": [100, 300]}

    return est, grid


# out-of-fold risk scores: settings are picked inside each training fold (nested CV)
def oof_scores(X, y, splits, name, seed):
    scores = np.zeros(len(y))
    chosen = []
    for train, held in splits:
        est, grid = model(name, seed)
        inner = StratifiedKFold(n_splits=3, shuffle=True, random_state=seed)
        search = GridSearchCV(est, grid, scoring="roc_auc", cv=inner, n_jobs=-1)
        search.fit(X[train], y[train])
        scores[held] = search.predict_proba(X[held])[:, 1]
        chosen.append(str(search.best_params_))

    return scores, chosen


# ranking quality, plus precision/recall when the top 20/30/50% are flagged
# best_f1 picks its cutoff on these same scores, so it's a little optimistic
def metrics(y, scores):
    precision, recall, _ = precision_recall_curve(y, scores)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
    out = {
        "roc_auc": roc_auc_score(y, scores),
        "pr_auc": average_precision_score(y, scores),
        "best_f1": f1.max(),
    }

    order = np.argsort(-scores, kind="stable")
    for share in SHARES:
        flagged = np.zeros(len(y), dtype=int)
        flagged[order[: round(share * len(y))]] = 1
        tp = int((flagged & y).sum())
        pct = int(share * 100)
        out[f"precision_{pct}"] = tp / flagged.sum()
        out[f"recall_{pct}"] = tp / y.sum()
        out[f"f1_{pct}"] = f1_score(y, flagged)

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True, choices=["e2", "e3"], help="e2: compare classifiers, e3: feature steps and samples")
    ap.add_argument("--features", default="outputs/features_train.csv", help="the training feature table")
    ap.add_argument("--models", default="lr,rf,gb", help="comma-separated: lr, rf, gb")
    ap.add_argument("--targets", default="a,b", help="comma-separated: a, b")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--out", required=True, help="CSV of mean and std per setup")
    ap.add_argument("--scores_out", help="CSV of every question's out-of-fold score, for the routing rehearsal")
    args = ap.parse_args()

    assert "test" not in Path(args.features).name, "train.py only reads the training table"
    models = args.models.split(",")
    targets = args.targets.split(",")
    assert set(models) <= set(MODELS) and set(targets) <= set(TARGETS), "unknown model or target"

    df = pd.read_csv(args.features)
    # log scale for row counts; trees don't care, logistic regression does
    df["sql_rows"] = np.log1p(df["sql_rows"])
    db = pd.get_dummies(df["db_id"], prefix="db", dtype=int)
    df = pd.concat([df, db], axis=1)

    # E2 also checks transfer to unseen databases; E3 uses 5-fold only
    cvs = ["5fold", "lodo"] if args.exp == "e2" else ["5fold"]

    results, score_tables = [], []
    for set_name, cols in feature_sets(args.exp, list(db.columns)).items():
        assert not NOT_FEATURES & set(cols), f"{set_name} includes a column that isn't a feature"
        X = df[cols].to_numpy(dtype=float)

        for t in targets:
            y = df[TARGETS[t]].to_numpy(dtype=int)
            for name in models:
                for cv in cvs:
                    per_seed, chosen = [], []
                    for seed in range(args.seeds):
                        if cv == "5fold":
                            splits = list(StratifiedKFold(n_splits=5, shuffle=True, random_state=seed).split(X, y))
                        else:
                            splits = list(LeaveOneGroupOut().split(X, y, groups=df["db_id"]))

                        scores, picked = oof_scores(X, y, splits, name, seed)
                        per_seed.append(metrics(y, scores))
                        chosen += picked
                        score_tables.append(pd.DataFrame({
                            "idx": df["idx"],
                            "question_id": df["question_id"],
                            "target": t,
                            "model": name,
                            "features": set_name,
                            "cv": cv,
                            "seed": seed,
                            "score": scores.round(6),
                        }))

                    row = {
                        "features": set_name, 
                        "target": t, 
                        "model": name, 
                        "cv": cv, 
                        "n_features": len(cols)
                    }
                    
                    for m in per_seed[0]:
                        vals = [p[m] for p in per_seed]
                        row[f"{m}_mean"] = round(float(np.mean(vals)), 4)
                        row[f"{m}_std"] = round(float(np.std(vals, ddof=1)), 4) if len(vals) > 1 else 0.0

                    row["usual_settings"] = Counter(chosen).most_common(1)[0][0]
                    results.append(row)
                    print(f"{set_name:18} {t}  {name}  {cv:5}  ROC-AUC {row['roc_auc_mean']:.3f} +- {row['roc_auc_std']:.3f}"
                          f"  PR-AUC {row['pr_auc_mean']:.3f} +- {row['pr_auc_std']:.3f}  F1@30% {row['f1_30_mean']:.3f}", flush=True)

    pd.DataFrame(results).to_csv(args.out, index=False)
    print(f"saved {len(results)} setups to {args.out}")
    if args.scores_out:
        pd.concat(score_tables).to_csv(args.scores_out, index=False)
        print(f"saved out-of-fold scores to {args.scores_out}")


if __name__ == "__main__":
    main()
