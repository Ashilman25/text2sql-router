import argparse
import json
import sqlite3
import time
from collections import defaultdict
from multiprocessing import Pool

from tqdm import tqdm


# run one query read-only with a time limit; returns (status, set of rows, seconds)
def run(db_path, sql, limit):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    start = time.time()
    con.set_progress_handler(lambda: int(time.time() - start > limit), 10000)
    
    try:
        return "ok", set(con.execute(sql).fetchall()), time.time() - start
    
    except sqlite3.OperationalError as e:
        status = "timeout" if "interrupted" in str(e) else "error"
        return status, None, time.time() - start
    
    except Exception:
        return "error", None, time.time() - start
    
    finally:
        con.close()


# score every sample of one question against the gold result
def check(job):
    row, db_path, gold_sql, limit = job
    gold_status, gold, gold_secs = run(db_path, gold_sql, limit)
    results, samples = [], []
    
    for s in row["samples"]:
        status, res, secs = run(db_path, s["sql"], max(1, limit - gold_secs))
        results.append(res)
        samples.append({
            "correct": int(gold is not None and res == gold),
            "status": status,
            "rows": None if res is None else len(res),
            "group": None if res is None else results.index(res),
            "seconds": round(secs, 2),
        })
        
    return {
        "idx": row["idx"],
        "question_id": row["question_id"],
        "db_id": row["db_id"],
        "difficulty": row["difficulty"],
        "model": row["model"],
        "gold_status": gold_status,
        "gold_seconds": round(gold_secs, 2),
        "samples": samples,
    }


# print EX by difficulty, plus how often the samples agree when there are several
def summarize(results):
    by_diff = defaultdict(list)
    for r in results:
        by_diff[r["difficulty"]].append(r["samples"][0]["correct"])
        
    for diff in ["simple", "moderate", "challenging"]:
        if by_diff[diff]:
            print(f"{diff:<12} {100 * sum(by_diff[diff]) / len(by_diff[diff]):6.2f}  ({len(by_diff[diff])} questions)")
            
    total = [r["samples"][0]["correct"] for r in results]
    print(f"{'total':<12} {100 * sum(total) / len(total):6.2f}  ({len(total)} questions, sample 0)")

    n_samples = len(results[0]["samples"])
    if n_samples > 1:
        distinct = [len({s["group"] for s in r["samples"] if s["group"] is not None}) + sum(s["group"] is None for s in r["samples"]) for r in results]
        all_same = sum(d == 1 for d in distinct)
        
        print(f"all {n_samples} samples gave the same result: {all_same} of {len(results)} questions ({100 * all_same / len(results):.1f}%)")
        print(f"average distinct results per question: {sum(distinct) / len(distinct):.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True, help="the question file the cache was made from")
    ap.add_argument("--db_root", required=True, help="folder holding <db_id>/<db_id>.sqlite")
    ap.add_argument("--cache", required=True, help="a .jsonl file written by generate.py")
    ap.add_argument("--out", help="defaults to the cache path ending in _check.jsonl")
    ap.add_argument("--timeout", type=float, default=400, help="seconds for gold plus prediction, like --meta_time_out")
    ap.add_argument("--num_cpus", type=int, default=8)
    args = ap.parse_args()

    with open(args.questions) as f:
        questions = json.load(f)
    with open(args.cache) as f:
        rows = [json.loads(line) for line in f if line.strip()]

    jobs = []
    for row in sorted(rows, key=lambda r: r["idx"]):
        q = questions[row["idx"]]
        assert q["question_id"] == row["question_id"], f"question {row['idx']} doesn't match the cache"
        db_path = f"{args.db_root.rstrip('/')}/{q['db_id']}/{q['db_id']}.sqlite"
        jobs.append((row, db_path, q["SQL"], args.timeout))

    with Pool(args.num_cpus) as pool:
        results = list(tqdm(pool.imap_unordered(check, jobs), total=len(jobs)))
        
    results.sort(key=lambda r: r["idx"])

    out = args.out or args.cache.removesuffix(".jsonl") + "_check.jsonl"
    with open(out, "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in results)
    print(f"saved {len(results)} checked questions to {out}")
    summarize(results)


if __name__ == "__main__":
    main()
