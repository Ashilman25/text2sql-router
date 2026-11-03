import argparse
from collections import defaultdict

import numpy as np
import pandas as pd

from features import load_jsonl
from route import DIFFICULTY, SHARES, TIE_SEED, curves, majority, ranks, router

TRIES = 5
TOGETHER = [1, 3, 5]
MAIN_A = "a lr plus_agree_k1"

# every E4 router: extra tries it needs and whether it decides before the 7B answers
ROUTERS = {
    "random": (0, True),
    "difficulty": (0, True),
    "crash rule": (0, False),
    "agreement rule": (5, False),
    "oracle": (0, False),
    "a lr plus_agree_k1": (1, False),
    "b gb plus_answer": (0, False),
    "a lr plus_agree_k1 maj": (5, False),
    "a lr plus_answer": (0, False),
    "a lr plus_agree_k3": (3, False),
    "a lr plus_agree_k5": (5, False),
    "a lr before_generation": (0, True),
}


# per-question seconds from the saved model runs 
def saved_times(runs):
    small = load_jsonl(f"{runs}_qwen7b.jsonl")
    tries = load_jsonl(f"{runs}_qwen7b_s5.jsonl")
    large = load_jsonl(f"{runs}_qwen32b.jsonl")
    return {
        "answer": np.array([r["samples"][0]["seconds"] for r in small]),
        "tries": np.array([[s["seconds"] for s in r["samples"]] for r in tries]),
        "together": {},
        "large": np.array([r["samples"][0]["seconds"] for r in large]),
    }


# per-question seconds from timing.py
# together = wall-clock until the last call returns
def timing_times(path, n, question_ids, saved_sql):
    passes = defaultdict(dict)
    for row in load_jsonl(path):
        passes[row["pass"]][row["idx"]] = row

    for name, rows in passes.items():
        assert sorted(rows) == list(range(n)), f"timing pass {name} doesn't cover all {n} questions"
        assert [rows[i]["question_id"] for i in range(n)] == question_ids, f"timing pass {name} isn't for these questions"

    assert "sequential" in passes and "large" in passes, "the timing file needs the sequential and large passes"
    seq = [passes["sequential"][i]["calls"] for i in range(n)]
    out = {
        "answer": np.array([c[0]["seconds"] for c in seq]),
        "tries": np.array([[t["seconds"] for t in c[1:]] for c in seq]),
        "together": {k: np.array([passes[f"together_{k}"][i]["seconds"] for i in range(n)]) for k in TOGETHER if f"together_{k}" in passes},
        "large": np.array([passes["large"][i]["calls"][0]["seconds"] for i in range(n)]),
    }

    # the timed replies are thrown away; this shows how often they differ from the saved ones
    for name, model in [("sequential", "small"), *((f"together_{k}", "small") for k in out["together"]), ("large", "large")]:
        same = sum(passes[name][i]["calls"][0]["sql"] == saved_sql[model][i] for i in range(n))
        print(f"timing {name:11} answer SQL same as the saved run: {same}/{n}")

    return out


# mean of each quantity after escalating the first m questions, for m = 0 to n
# per question: what every question costs, plus the extra an escalated one costs
def curve(order, base, extra):
    n = len(base)
    if order is None:
        return (base.sum() + np.arange(n + 1) / n * extra.sum()) / n

    return (base.sum() + np.concatenate([[0], np.cumsum(extra[order])])) / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default="outputs/features_test.csv", help="feature table of the routed questions")
    ap.add_argument("--scores", default="outputs/e4_scores.csv", help="risk scores from route.py --mode final")
    ap.add_argument("--routers", default="outputs/e4_routers.csv", help="E4 router table; EX here must match it")
    ap.add_argument("--runs", default="outputs/minidev", help="start of the run file names")
    ap.add_argument("--timing", help="timing file from timing.py; without it, the saved runs' seconds are used")
    ap.add_argument("--agree_rule", type=int, default=2, help="j in 'at most j of 5 tries agree' (frozen: 2)")
    ap.add_argument("--price_in", type=float, required=True, help="32B price, dollars per million input tokens")
    ap.add_argument("--price_out", type=float, required=True, help="32B price, dollars per million output tokens")
    ap.add_argument("--out", default="outputs/e5", help="start of the output file names")
    args = ap.parse_args()

    df = pd.read_csv(args.features)
    scores = pd.read_csv(args.scores)
    n = len(df)
    assert (df["idx"] == np.arange(n)).all() and (scores["idx"] == np.arange(n)).all(), "tables aren't in idx order"
    assert (scores["question_id"] == df["question_id"]).all(), "scores and features are for different questions"
    question_ids = df["question_id"].tolist()

    checks = {name: load_jsonl(f"{args.runs}_{name}_check.jsonl") for name in ["qwen7b", "qwen32b", "qwen7b_s5"]}
    gens = {name: load_jsonl(f"{args.runs}_{name}.jsonl") for name in ["qwen7b", "qwen32b", "qwen7b_s5"]}
    for name, rows in [*checks.items(), *gens.items()]:
        assert [r["question_id"] for r in rows] == question_ids, f"{name} doesn't match the feature table"

    small = np.array([r["samples"][0]["correct"] for r in checks["qwen7b"]])
    large = np.array([r["samples"][0]["correct"] for r in checks["qwen32b"]])
    major = np.array([majority(r) for r in checks["qwen7b_s5"]])

    # the same queues as route.py --mode final
    tiebreak = np.random.default_rng(TIE_SEED).permutation(n)
    one_fold = np.zeros(n, dtype=int)
    rank_scores = {
        "difficulty": df["difficulty"].map(DIFFICULTY).to_numpy(),
        "crash rule": df["sql_crashed"].to_numpy(),
        "agreement rule": -df["agree_k5"].to_numpy(),
        "oracle": large - small,
        **{name: scores[name].to_numpy() for name in scores.columns if name not in ("idx", "question_id")},
        "a lr plus_agree_k1 maj": scores[MAIN_A].to_numpy(),
    }
    routers = {"random": router(small, None, tiebreak)}
    for name in ROUTERS:
        if name != "random":
            kept = major if name.endswith(" maj") else small
            routers[name] = router(kept, [(rank_scores[name], one_fold)], tiebreak)

    # EX must be exactly E4's, so the escalated questions are the same ones
    e4 = pd.read_csv(args.routers).set_index("router")
    ex = {name: curves(r, large)[0] for name, r in routers.items()}
    for name in ROUTERS:
        for s in SHARES:
            got, want = round(ex[name][round(s * n)], 2), e4.loc[name, f"ex_{int(s * 100)}"]
            assert abs(got - want) < 0.005, f"{name} at {s:.0%}: EX {got} here, {want} in E4"
    print(f"EX matches E4 for all {len(ROUTERS)} routers at 20 / 30 / 50%")

    # seconds per question
    saved_sql = {
        "small": [r["samples"][0]["sql"] for r in gens["qwen7b"]],
        "large": [r["samples"][0]["sql"] for r in gens["qwen32b"]],
    }
    t = timing_times(args.timing, n, question_ids, saved_sql) if args.timing else saved_times(args.runs)
    run_small = np.array([r["samples"][0]["seconds"] for r in checks["qwen7b"]])
    run_tries = np.array([[s["seconds"] for s in r["samples"]] for r in checks["qwen7b_s5"]])
    run_large = np.array([r["samples"][0]["seconds"] for r in checks["qwen32b"]])

    print(f"\nseconds per question ({'timing run' if args.timing else 'saved runs'}), mean over {n}")
    print(f"7B answer {t['answer'].mean():.3f}, each try {t['tries'].mean():.3f}, 5 tries in a row {t['tries'].sum(axis=1).mean():.3f}")
    for k, v in t["together"].items():
        print(f"answer + {k} {'try' if k == 1 else 'tries'} together {v.mean():.3f}")
    print(f"32B answer {t['large'].mean():.3f}")
    print(f"running the SQL: 7B answer {run_small.mean():.3f}, 5 tries {run_tries.sum(axis=1).mean():.3f}, 32B answer {run_large.mean():.3f}")

    # tokens and dollars: the replies the routers actually used
    tok_small = np.array([r["samples"][0]["prompt_tokens"] + r["samples"][0]["output_tokens"] for r in gens["qwen7b"]])
    tok_tries = np.array([[s["prompt_tokens"] + s["output_tokens"] for s in r["samples"]] for r in gens["qwen7b_s5"]])
    large_in = np.array([r["samples"][0]["prompt_tokens"] for r in gens["qwen32b"]])
    large_out = np.array([r["samples"][0]["output_tokens"] for r in gens["qwen32b"]])
    usd = (large_in * args.price_in + large_out * args.price_out) / 1e6
    print(f"tokens per question: 7B answer {tok_small.mean():.0f}, 32B prompt {large_in.mean():.0f} + reply {large_out.mean():.0f}")
    print(f"32B price ${args.price_in} / ${args.price_out} per million in / out: ${1000 * usd.mean():.3f} per 1,000 questions sent up")

    small_call = t["answer"] + run_small
    large_call = t["large"] + run_large
    frames = []
    for name, (k, before) in ROUTERS.items():
        ranks_ = routers[name]["ranks"]
        order = None if ranks_ is None else np.argsort(ranks_[0])
        if before:
            # escalated questions skip the 7B entirely
            seq = together = curve(order, small_call, large_call - small_call)
            tok = curve(order, tok_small, -tok_small)
        else:
            tries_run = run_tries[:, :k].sum(axis=1)
            seq = curve(order, small_call + t["tries"][:, :k].sum(axis=1) + tries_run, large_call)
            both = t["answer"] if k == 0 else t["together"].get(k)
            together = curve(order, both + run_small + tries_run, large_call) if both is not None else np.full(n + 1, np.nan)
            tok = curve(order, tok_small + tok_tries[:, :k].sum(axis=1), np.zeros(n))

        frames.append(pd.DataFrame({
            "router": name,
            "tries": k,
            "escalated": np.arange(n + 1),
            "share": np.arange(n + 1) / n,
            "ex": ex[name].round(4),
            "seconds_in_a_row": seq.round(4),
            "seconds_together": together.round(4),
            "usd_per_1000": (1000 * curve(order, np.zeros(n), usd)).round(4),
            "tokens_small": tok.round(1),
            "tokens_large": curve(order, np.zeros(n), (large_in + large_out).astype(float)).round(1),
        }))
    table = pd.concat(frames, ignore_index=True)

    # reference points: always-small, always-large, fixed shares, rules at their own share, matching always-large
    large_ex = 100 * large.mean()
    large_row = {
        "router": "always large",
        "point": "100%",
        "tries": 0,
        "escalated": n,
        "share": 1.0,
        "ex": round(large_ex, 4),
        "seconds_in_a_row": large_call.mean(),
        "seconds_together": large_call.mean(),
        "usd_per_1000": 1000 * usd.mean(),
        "tokens_small": 0.0,
        "tokens_large": float((large_in + large_out).mean()),
    }
    small_row = table[(table["router"] == "crash rule") & (table["escalated"] == 0)].iloc[0].to_dict() | {"router": "always small", "point": "0%"}
    own = {
        "crash rule": int(df["sql_crashed"].sum()),
        "agreement rule": int((df["agree_k5"] <= args.agree_rule).sum()),
    }
    own[MAIN_A] = own["agreement rule"]

    points = [small_row]
    for name in ROUTERS:
        rows = table[table["router"] == name]
        marks = [(f"{s:.0%}", round(s * n)) for s in SHARES]
        if name in own:
            marks.append(("rule's share", own[name]))
        reach = rows.index[rows["ex"] >= large_ex - 1e-9]
        if len(reach):
            marks.append(("matches always large", int(rows.loc[reach[0], "escalated"])))
        for label, m in marks:
            points.append(rows[rows["escalated"] == m].iloc[0].to_dict() | {"point": label})
    points.append(large_row)

    pts = pd.DataFrame(points)
    pts["usd_vs_large"] = (100 * pts["usd_per_1000"] / large_row["usd_per_1000"]).round(1)
    cols = [
        "router", "point", "tries", "escalated", "share", "ex", "seconds_in_a_row", "seconds_together",
        "usd_per_1000", "usd_vs_large", "tokens_small", "tokens_large"
    ]
    pts = pts[cols].round(4)

    print("\nper question: EX, seconds with the tries in a row / together, $ per 1,000 questions, $ as % of always-large")
    for row in pts.to_dict("records"):
        print(f"{row['router']:24} {row['point']:20} k={row['tries']}  {row['share']:6.1%}  EX {row['ex']:6.2f}  "
              f"{row['seconds_in_a_row']:6.3f} / {row['seconds_together']:6.3f} s  ${row['usd_per_1000']:6.3f}  {row['usd_vs_large']:5.1f}%")

    table.to_csv(f"{args.out}_curves.csv", index=False)
    pts.to_csv(f"{args.out}_points.csv", index=False)
    print(f"\nsaved {args.out}_curves.csv and {args.out}_points.csv")


if __name__ == "__main__":
    main()
