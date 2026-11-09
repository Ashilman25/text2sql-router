import argparse
import json

import numpy as np
import pandas as pd
from scipy.stats import binomtest

from features import load_jsonl
from train import NOT_FEATURES, TARGETS, feature_sets, model

SEP = "\t----- bird -----\t"
SHARES = [0.2, 0.3, 0.5]
AREA = (0.1, 0.5)
BOOT = 10_000
BOOT_SEED = 0
TIE_SEED = 0
DIFFICULTY = {
    "simple": 0, 
    "moderate": 1, 
    "challenging": 2
}
# difficulty is skipped for question sets without BIRD's labels
BASELINES = ["random", "difficulty", "crash rule", "agreement rule"]

# classifier candidates; before_generation is only a comparison curve, never picked
CANDIDATES = [("a", "lr"), ("a", "gb"), ("b", "gb")]
STEPS = ["before_generation", "plus_answer", "plus_agree_k1", "plus_agree_k3", "plus_agree_k5"]
SAMPLES = {
    "plus_answer": 0,
    "plus_agree_k1": 1,
    "plus_agree_k3": 3,
    "plus_agree_k5": 5,
}

# frozen for the test run (journal, 27 Oct): target, classifier, feature set, settings
MAIN_A, MAIN_B = "a lr plus_agree_k1", "b gb plus_answer"
FROZEN = {
    MAIN_A: ("a", "lr", "plus_agree_k1", {"logisticregression__C": 1}),
    MAIN_B: ("b", "gb", "plus_answer", {"max_depth": 1, "max_iter": 50}),
}

# extra test-run curves (cost trade-off, question only); no hypothesis is decided on them
EXTRA = {
    "a lr plus_answer": ("a", "lr", "plus_answer", {"logisticregression__C": 1}),
    "a lr plus_agree_k3": ("a", "lr", "plus_agree_k3", {"logisticregression__C": 1}),
    "a lr plus_agree_k5": ("a", "lr", "plus_agree_k5", {"logisticregression__C": 1}),
    "a lr before_generation": ("a", "lr", "before_generation", {"logisticregression__C": 0.001}),
}


# right/wrong of the most common result among samples that ran
# ties go to the earlier sample
def majority(row):
    groups = [s["group"] for s in row["samples"] if s["group"] is not None]
    if not groups:
        return 0

    best = max(set(groups), key=lambda g: (groups.count(g), -g))
    return row["samples"][best]["correct"]


# escalation rank per question: highest score first, every fold escalated at the same pace,
# ties broken by a fixed random order
def ranks(score, fold, tiebreak):
    key = np.zeros(len(score))
    for f in np.unique(fold):
        members = np.flatnonzero(fold == f)
        ordered = members[np.lexsort((tiebreak[members], -score[members]))]
        key[ordered] = (np.arange(len(ordered)) + 0.5) / len(ordered)

    rank = np.empty(len(score), dtype=int)
    rank[np.lexsort((tiebreak, key))] = np.arange(len(score))
    return rank


# the router - the answer it keeps, and one escalation rank per run (seed)
# no ranks = random
def router(kept, runs, tiebreak):
    return {
        "kept": kept,
        "ranks": None if runs is None else [ranks(score, fold, tiebreak) for score, fold in runs],
    }


# EX % after escalating the first m questions
# for m = 0 to n, one row per run
def curves(r, large):
    kept, n = r["kept"], len(r["kept"])
    gain = large - kept
    if r["ranks"] is None:
        return np.array([100 * (kept.sum() + np.arange(n + 1) / n * gain.sum()) / n])

    return np.array([100 * (kept.sum() + np.concatenate([[0], np.cumsum(gain[np.argsort(rank)])])) / n for rank in r["ranks"]])


# each question's outcome with the first m escalated (1 right, 0 wrong), one row per run
def outcomes(r, large, m):
    kept = r["kept"]
    gain = large - kept
    if r["ranks"] is None:
        return np.array([kept + gain * m / len(kept)])

    return np.array([kept + gain * (rank < m) for rank in r["ranks"]])


# each question's average outcome over m = lo to hi escalated, averaged over runs
def area_outcomes(r, large, lo, hi):
    kept = r["kept"]
    gain = large - kept
    if r["ranks"] is None:
        return kept + gain * (lo + hi) / 2 / len(kept)

    covered = [np.clip(hi - np.maximum(lo, rank + 1) + 1, 0, None) / (hi - lo + 1) for rank in r["ranks"]]
    return kept + gain * np.mean(covered, axis=0)


# EX at the fixed shares, mean EX over a range of shares, and the share matching always-large
def summary(name, r, large):
    n = len(large)
    c = curves(r, large)
    lo, hi = (round(a * n) for a in AREA)
    vals = {
        **{f"ex_{int(s * 100)}": c[:, round(s * n)] for s in SHARES},
        "area_10_50": c[:, lo:hi + 1].mean(axis=1),
        "area_all": c.mean(axis=1),
        "match_large": np.array([100 * np.argmax(run >= c[0, n] - 1e-9) / n for run in c]),
    }

    row = {
        "router": name, 
        "runs": len(c)
    }

    for k, v in vals.items():
        row[k] = round(float(v.mean()), 2)
        row[f"{k}_std"] = round(float(v.std(ddof=1)), 2) if len(v) > 1 else 0.0

    return row


# EX at a rule's own escalation point, where no ties need breaking, and random at that share
def point(mask, kept, large):
    n, m = len(kept), int(mask.sum())
    ex = 100 * np.where(mask, large, kept).sum() / n
    random = 100 * (kept.sum() + m / n * (large - kept).sum()) / n
    return m, ex, random


# 95% range of a paired difference in EX
def boot_range(diff, boot):
    return np.percentile(100 * boot @ diff / len(diff), [2.5, 97.5])


# exact McNemar p-value for two right/wrong vectors on the same questions
def mcnemar(x, y):
    b, c = int(((x == 1) & (y == 0)).sum()), int(((x == 0) & (y == 1)).sum())
    return binomtest(b, b + c).pvalue if b + c else 1.0


# paired comparison of per-question outcomes
# Mcnemar only when both are plain right/wrong 
def compare(x, y, boot, concrete):
    diff = x.mean(axis=0) - y.mean(axis=0)
    low, high = boot_range(diff, boot)
    p = max(float(mcnemar(x[i % len(x)], y[i % len(y)])) for i in range(max(len(x), len(y)))) if concrete else None
    return {
        "ex": round(float(100 * x.mean()), 2),
        "ex_baseline": round(float(100 * y.mean()), 2),
        "diff": round(float(100 * diff.mean()), 2),
        "ci_low": round(float(low), 2),
        "ci_high": round(float(high), 2),
        "includes_zero": bool(low <= 0 <= high),
        "mcnemar_p": p,
    }


# compare two routers with the first m questions escalated by each
def test(name, r, base_name, base, large, m, label, boot):
    return {
        "router": name,
        "baseline": base_name,
        "share": label,
        "escalated": m,
        **compare(outcomes(r, large, m), outcomes(base, large, m), boot, r["ranks"] is not None and base["ranks"] is not None),
    }


# one printed cell: share, difference [95% range] and McNemar p
def cell(row):
    return f"{row['share']}: {row['diff']:+.2f} [{row['ci_low']:+.2f}, {row['ci_high']:+.2f}] p {row['mcnemar_p']:.2g}"


# feature matrix prepared as in train.py: row counts on a log scale
def prepare(df, cols):
    return df.assign(sql_rows=np.log1p(df["sql_rows"]))[cols].to_numpy(dtype=float)


# rehearsal routers from the saved out-of-fold scores, one run per seed
def rehearsal_routers(path, n, small, major, tiebreak):
    scores = pd.read_csv(path)
    scores = scores[scores["cv"] == "5fold"]
    routers = {}
    
    for target, clf in CANDIDATES:
        for step in STEPS:
            name = f"{target} {clf} {step}"
            sel = scores[(scores["target"] == target) & (scores["model"] == clf) & (scores["features"] == step)]
            runs = []
            for seed, run in sel.groupby("seed"):
                run = run.sort_values("idx")
                assert (run["idx"].to_numpy() == np.arange(n)).all(), f"{name} seed {seed} doesn't cover every question"
                runs.append((run["score"].to_numpy(), run["fold"].to_numpy()))

            assert runs, f"no scores for {name}"
            routers[name] = router(small, runs, tiebreak)
            if step == "plus_agree_k5":
                routers[f"{name} maj"] = router(major, runs, tiebreak)

    return routers


# test-run routers: each frozen classifier fit once on every training question, then one score each
def final_routers(train, test, small, major, tiebreak):
    one_fold = np.zeros(len(test), dtype=int)
    routers, scores = {}, {}
    for name, (target, clf, step, settings) in {**FROZEN, **EXTRA}.items():
        cols = feature_sets("e3", [])[step]
        assert not NOT_FEATURES & set(cols), f"{name} includes a column that isn't a feature"
        
        est, _ = model(clf, 0)
        est.set_params(**settings)
        est.fit(prepare(train, cols), train[TARGETS[target]].to_numpy(dtype=int))
        
        scores[name] = est.predict_proba(prepare(test, cols))[:, 1]
        routers[name] = router(small, [(scores[name], one_fold)], tiebreak)
        if name == MAIN_A:
            routers[f"{name} maj"] = router(major, [(scores[name], one_fold)], tiebreak)

    return routers, scores


# rehearsal selection: best mean EX over 10-50%, or the cheapest version within noise of it
def select(classifiers, large, boot):
    n = len(large)
    lo, hi = (round(a * n) for a in AREA)
    rows = []
    
    print("\nselection: mean EX over 10-50% escalated, difference from the best for the same target [95% range]")
    for target in ["a", "b"]:
        family = [f"{t} {clf} {step}" for t, clf in CANDIDATES if t == target for step in SAMPLES]
        area = {f: area_outcomes(classifiers[f], large, lo, hi)[None] for f in family}
        best = max(family, key=lambda f: area[f].mean())
        eligible = []

        for f in family:
            row = {
                "router": f,
                "baseline": best,
                "share": "10-50% mean",
                "escalated": None,
                **compare(area[f], area[best], boot, False)
            }
            rows.append(row)
            if row["includes_zero"]:
                eligible.append(f)

            note = "best" if f == best else ("within noise" if row["includes_zero"] else "")
            print(f"{f:28} {row['ex']:6.2f} {row['diff']:+6.2f} [{row['ci_low']:+.2f}, {row['ci_high']:+.2f}] {note}")

        pick = min(eligible, key=lambda f: (SAMPLES[f.split()[2]], f.split()[1] != "lr"))
        print(f"pick: {pick} (fewest samples, then simpler classifier, within noise of the best)")

    return rows


# scorer-format predictions: the 32B's SQL for escalated questions, the 7B's for the rest
def write_routed(path, small_preds, large_preds, escalated):
    routed = {k: large_preds[k] if escalated[int(k)] else small_preds[k] for k in small_preds}
    with open(path, "w") as f:
        json.dump(routed, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rehearse", "final"], default="rehearse", help="rehearse on training out-of-fold scores, or final: the one E4 run")
    ap.add_argument("--features", default="outputs/features_train.csv", help="the training feature table")
    ap.add_argument("--test_features", help="final mode: the feature table of the questions to route")
    ap.add_argument("--runs", default="outputs/train", help="start of the run file names of the routed questions")
    ap.add_argument("--scores", default="outputs/e3_scores.csv", help="rehearse mode: out-of-fold scores (with folds) from train.py")
    ap.add_argument("--agree_rule", type=int, choices=range(5), help="j in 'at most j of 5 samples agree'; rehearse default: the best on this data")
    ap.add_argument("--out", default="outputs/rehearsal", help="start of the output file names")
    args = ap.parse_args()

    assert "test" not in args.features and "minidev" not in args.features, "--features must be the training table"
    train = pd.read_csv(args.features)
    if args.mode == "rehearse":
        assert "minidev" not in args.runs, "the rehearsal only reads training files"
        df = train

    else:
        assert args.test_features and args.agree_rule is not None, "final mode needs --test_features and the frozen --agree_rule"
        df = pd.read_csv(args.test_features)
        assert list(df.columns) == list(train.columns), "the two feature tables have different columns"
        if args.test_features == args.features:
            print("dry run: the training questions are routed by classifiers fit on them, so the numbers mean nothing\n")

    n = len(df)
    assert (df["idx"] == np.arange(n)).all(), "the feature table isn't in idx order"
    checks = {name: load_jsonl(f"{args.runs}_{name}_check.jsonl") for name in ["qwen7b", "qwen32b", "qwen7b_s5"]}
    for name, rows in checks.items():
        assert [r["question_id"] for r in rows] == df["question_id"].tolist(), f"{name} doesn't match the feature table"

    small = np.array([r["samples"][0]["correct"] for r in checks["qwen7b"]])
    large = np.array([r["samples"][0]["correct"] for r in checks["qwen32b"]])
    major = np.array([majority(r) for r in checks["qwen7b_s5"]])
    assert (small == 1 - df["label_a"]).all() and (df["label_b"] == (1 - small) * large).all(), "labels don't match the checks"

    print(f"always small (7B) {100 * small.mean():.2f}")
    print(f"always large (32B) {100 * large.mean():.2f}")
    fixes, breaks = int(((major == 1) & (small == 0)).sum()), int(((major == 0) & (small == 1)).sum())
    print(f"majority answer kept {100 * major.mean():.2f} (fixes {fixes}, breaks {breaks})")

    # rule routers at their own shares
    # where the answer doesnt depend on a tiebreak
    agree = df["agree_k5"].to_numpy()
    has_difficulty = bool(df["difficulty"].notna().all())
    points = [
        ("crashed", df["sql_crashed"].to_numpy() == 1, small),
        *[(f"at most {j} of 5 agree", agree <= j, small) for j in range(5)],
        *([
            ("challenging", df["difficulty"].to_numpy() == "challenging", small),
            ("challenging + moderate", df["difficulty"].to_numpy() != "simple", small),
        ] if has_difficulty else []),
        ("oracle", large - small == 1, small),
        ("oracle, majority kept", large - major == 1, major),
    ]
    print("\nrule routers at their own shares")
    gains = {}
    for label, mask, kept in points:
        m, ex, rand = point(mask, kept, large)
        gains[label] = ex - rand
        print(f"{label:24} {100 * m / n:5.1f}% EX {ex:6.2f} random {rand:6.2f} gain {ex - rand:+.2f}")

    j = args.agree_rule if args.agree_rule is not None else max(range(5), key=lambda j: gains[f"at most {j} of 5 agree"])
    m_rule = int((agree <= j).sum())
    rule_label = f"{m_rule / n:.1%}"
    print(f"agreement rule to beat (H3): at most {j} of 5 agree, {rule_label} escalated")

    tiebreak = np.random.default_rng(TIE_SEED).permutation(n)
    one_fold = np.zeros(n, dtype=int)
    refs = {
        "random": router(small, None, tiebreak),
        **({"difficulty": router(small, [(df["difficulty"].map(DIFFICULTY).to_numpy(), one_fold)], tiebreak)} if has_difficulty else {}),
        "crash rule": router(small, [(df["sql_crashed"].to_numpy(), one_fold)], tiebreak),
        "agreement rule": router(small, [(-agree, one_fold)], tiebreak),
        "oracle": router(small, [(large - small, one_fold)], tiebreak),
    }

    if args.mode == "rehearse":
        classifiers = rehearsal_routers(args.scores, n, small, major, tiebreak)
        pairs = [(f"b gb {step}", f"a {clf} {step}") for step in SAMPLES for clf in ["lr", "gb"]]

    else:
        classifiers, test_scores = final_routers(train, df, small, major, tiebreak)
        pairs = [(MAIN_B, MAIN_A)]

    table = pd.DataFrame([summary(name, r, large) for name, r in {**refs, **classifiers}.items()])
    print("\nrouters, mean +- std over seeds: EX at 20 / 30 / 50% escalated, mean EX over 10-50% and 0-100%, share matching always-large")
    cols = ["ex_20", "ex_30", "ex_50", "area_10_50", "area_all", "match_large"]
    for row in table.to_dict("records"):
        print(f"{row['router']:28}", *(f"{row[k]:7.2f} +- {row[k + '_std']:.2f}" for k in cols))

    # how often each question is drawn in each bootstrap resample; shared by every comparison
    boot = np.random.default_rng(BOOT_SEED).multinomial(n, np.full(n, 1 / n), size=BOOT)
    tests = select(classifiers, large, boot) if args.mode == "rehearse" else []

    shares = {f"{s:.0%}": round(s * n) for s in SHARES}
    baselines = [b for b in BASELINES if b in refs]
    for name, r in classifiers.items():
        for base in baselines:
            for label, m in shares.items():
                tests.append(test(name, r, base, refs[base], large, m, label, boot))

        tests.append(test(name, r, "agreement rule", refs["agreement rule"], large, m_rule, rule_label, boot))

    t = pd.DataFrame(tests)
    print("\nEX difference vs baselines in points, * = 95% range excludes 0 (ranges and McNemar p in the tests CSV)")
    print("columns: " + ", ".join(f"{b} 20/30/50%" for b in baselines) + f", agreement rule at its own {rule_label}")
    for name in classifiers:
        cells = []
        for base in baselines:
            for label in [*shares, rule_label] if base == "agreement rule" else [*shares]:
                row = t[(t["router"] == name) & (t["baseline"] == base) & (t["share"] == label)].iloc[0]
                star = "" if row["includes_zero"] else "*"
                cells.append(f"{row['diff']:+7.2f}{star:1}")

        print(f"{name:28}" + "".join(cells))

    print("\nmajority answer kept vs temperature-0 answer kept, same ranking")
    for name, r in classifiers.items():
        if name.endswith(" maj"):
            base = name.removesuffix(" maj")
            rows = [test(name, r, base, classifiers[base], large, m, label, boot) for label, m in shares.items()]
            tests += rows
            print(f"{name:28}", *(cell(row) for row in rows))

    print("\nB vs A (H5)")
    for b, a in pairs:
        rows = [test(b, classifiers[b], a, classifiers[a], large, m, label, boot) for label, m in shares.items()]
        tests += rows
        print(f"{b:18} vs {a:18}", *(cell(row) for row in rows))

    frames = []
    for name, r in {**refs, **classifiers}.items():
        for run, c in enumerate(curves(r, large)):
            frames.append(pd.DataFrame({
                "router": name,
                "run": run,
                "escalated": np.arange(n + 1),
                "share": np.arange(n + 1) / n,
                "ex": c.round(4),
            }))

    table.to_csv(f"{args.out}_routers.csv", index=False)
    pd.DataFrame(tests).to_csv(f"{args.out}_tests.csv", index=False)
    pd.concat(frames).to_csv(f"{args.out}_curves.csv", index=False)
    print(f"\nsaved {args.out}_routers.csv, {args.out}_tests.csv and {args.out}_curves.csv")

    if args.mode == "final":
        pd.DataFrame({
            "idx": df["idx"], 
            "question_id": df["question_id"], 
            **test_scores
        }).to_csv(f"{args.out}_scores.csv", index=False)
        
        print(f"saved {args.out}_scores.csv (each question's risk score from every classifier)")

        preds = {}
        for name in ["qwen7b", "qwen32b"]:
            with open(f"{args.runs}_{name}.json") as f:
                preds[name] = json.load(f)

            assert list(preds[name]) == [str(i) for i in range(n)], f"{name}.json doesn't have one prediction per question"
            assert [p.split(SEP)[1] for p in preds[name].values()] == df["db_id"].tolist(), f"{name}.json doesn't match the questions"

        # files for the official scorer: both main routers at each share, and the H3 comparison
        routers = {**refs, **classifiers}
        files = [(name, label.rstrip("%"), m) for name in [MAIN_A, MAIN_B] for label, m in shares.items()]
        files += [(name, "rule", m_rule) for name in [MAIN_A, "agreement rule"]]
        for name, label, m in files:
            path = f"{args.out}_{name.replace(' ', '_')}_{label}.json"
            write_routed(path, preds["qwen7b"], preds["qwen32b"], routers[name]["ranks"][0] < m)
            print(f"saved {path}: {m} escalated, EX from the per-question marks {100 * outcomes(routers[name], large, m).mean():.2f}")


if __name__ == "__main__":
    main()
