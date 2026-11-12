import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from multiprocessing import Pool

from check import run

# placeholder labels so the official scorer has no empty difficulty group; only its total is used
PLACEHOLDER = ["simple", "moderate", "challenging"]


# run one gold query read-only; returns status, row count and whether it gave only NULLs
def gold(job):
    db_path, sql, limit = job
    status, rows, secs = run(db_path, sql, limit)
    null_only = rows is not None and len(rows) > 0 and all(v is None for r in rows for v in r)
    return status, None if rows is None else len(rows), null_only, secs


# the first exclusion rule a question breaks, or None if it can be sampled
def exclusion(q, g, duplicates):
    status, rows, null_only, _ = g
    if q["db_id"] == "retail_world":
        return "retail_world (gold written for another schema)"
    
    if status != "ok":
        return f"gold {status}"
    
    if rows == 0:
        return "gold returns no rows"
    
    if null_only:
        return "gold returns only NULL"
    
    #CLAUDE ASSISTED REGEX
    if re.search(r"\bLIMIT\b", q["SQL"], re.I) and not re.search(r"\bORDER\s+BY\b", q["SQL"], re.I):
        return "LIMIT without ORDER BY"
    
    return duplicates.get(q["question_id"])


# duplicate questions on the same database: drop all if gold differs, else keep the first
def find_duplicates(questions):
    groups = defaultdict(list)
    for q in questions:
        groups[(q["db_id"], q["question"].strip().lower())].append(q)

    out = {}
    for group in groups.values():
        if len(group) < 2:
            continue
        
        if len({" ".join(q["SQL"].split()).lower() for q in group}) > 1:
            out.update({q["question_id"]: "duplicate with different gold" for q in group})
        else:
            out.update({q["question_id"]: "repeat of an earlier question" for q in group[1:]})

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", help="folder with BIRD's train.json and train_databases/")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--cap", type=int, default=8, help="most questions taken from one database")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=400, help="seconds a gold query may take")
    ap.add_argument("--num_cpus", type=int, default=8)
    args = ap.parse_args()

    with open(f"{args.data_dir}/train.json") as f:
        raw = json.load(f)

    # BIRD's training file has no IDs or difficulty, so the ID is the position in train.json
    questions = [{
        "question_id": i, 
        "db_id": q["db_id"],
        "question": q["question"],
        "evidence": q.get("evidence") or "", 
        "SQL": q["SQL"], 
        "difficulty": None
    } for i, q in enumerate(raw)]
    
    root = f"{args.data_dir}/train_databases"
    jobs = [(f"{root}/{q['db_id']}/{q['db_id']}.sqlite", q["SQL"], args.timeout) for q in questions]
    
    with Pool(args.num_cpus) as pool:
        golds = pool.map(gold, jobs, chunksize=4)

    duplicates = find_duplicates(questions)
    reasons = [exclusion(q, g, duplicates) for q, g in zip(questions, golds)]
    print(f"{len(questions)} questions on {len({q['db_id'] for q in questions})} databases")
    for reason, count in Counter(r for r in reasons if r).most_common():
        print(f"  excluded, {reason}: {count}")
        
    print("  gold timeouts:", [q["question_id"] for q, g in zip(questions, golds) if g[0] == "timeout"])

    eligible = [q for q, r in zip(questions, reasons) if r is None]
    print(f"eligible: {len(eligible)} questions on {len({q['db_id'] for q in eligible})} databases")

    # one fixed random order over every question, so an exclusion only changes its own slot
    order = random.Random(args.seed).sample(range(len(questions)), len(questions))
    taken, per_db = [], Counter()
    for i in order:
        q = questions[i]
        if reasons[i] is None and per_db[q["db_id"]] < args.cap:
            taken.append(q)
            per_db[q["db_id"]] += 1
            
        if len(taken) == args.n:
            break

    assert len(taken) == args.n, f"only {len(taken)} questions could be sampled"
    taken.sort(key=lambda q: q["question_id"])

    with open(f"{args.data_dir}/unseen.json", "w") as f:
        json.dump(taken, f, indent=4)
        
    with open(f"{args.data_dir}/unseen_gold.sql", "w") as f:
        f.write("".join(f"{q['SQL']}\t{q['db_id']}\n" for q in taken))
        
    with open(f"{args.data_dir}/unseen_scorer.jsonl", "w") as f:
        f.write("".join(json.dumps({**q, "difficulty": PLACEHOLDER[i % 3]}) + "\n" for i, q in enumerate(taken)))

    counts = sorted(per_db.values())
    ids = ",".join(str(q["question_id"]) for q in taken)
    secs = sorted(golds[q["question_id"]][3] for q in taken)
    
    print(f"sampled {len(taken)} questions on {len(per_db)} databases, per database {counts[0]} to {counts[-1]}, {sum(c == args.cap for c in counts)} at the cap of {args.cap}")
    print(f"without a hint: {sum(not q['evidence'].strip() for q in taken)}, slowest gold: {secs[-1]:.1f} s, over 10 s: {sum(s > 10 for s in secs)}")
    print(f"sha256 of the sampled question_id list: {hashlib.sha256(ids.encode()).hexdigest()}")
    print(f"wrote unseen.json, unseen_gold.sql and unseen_scorer.jsonl to {args.data_dir}")


if __name__ == "__main__":
    main()
