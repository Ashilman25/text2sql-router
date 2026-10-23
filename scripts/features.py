import argparse
import csv
import json
import math
import re
import sqlite3

ID_COLUMNS = ["idx", "question_id", "db_id", "difficulty"]
LABELS = ["label_a", "label_b"]

# words in the question that hint at harder SQL (percentages, ranking, counting)
KEYWORDS = {
    "kw_percent": r"percent|%",
    "kw_ratio": r"\bratio\b|\btimes\b",
    "kw_average": r"\baverage\b|\bmean\b",
    "kw_highest": r"\bhighest\b|\bmost\b|\bmaximum\b|\blargest\b|\bbiggest\b|\btop\b",
    "kw_lowest": r"\blowest\b|\bleast\b|\bminimum\b|\bsmallest\b|\bfewest\b",
    "kw_count": r"\bhow many\b|\bnumber of\b|\bcount\b",
    "kw_total": r"\btotal\b|\bsum\b",
    "kw_difference": r"\bdifference\b|\bdiffer\b",
}

K_MAX = 5

# feature columns by group; agreement has one group per number of samples k
GROUPS = {
    "question": [
        "q_words", "q_has_number", *KEYWORDS, 
        "has_hint", "hint_words"
    ],
    "schema": [
        "db_tables", "db_columns", 
        "q_table_mentions", "q_column_mentions"
    ],
    "sql": [
        "sql_crashed", "sql_empty", 
        "sql_rows", "sql_joins", 
        "sql_subqueries", "sql_chars", "reply_tokens"
    ],
    "confidence": [
        "lp_mean", 
        "lp_min", "lp_low_count"
    ],
    **{f"agreement_k{k}": [
        f"agree_k{k}", f"distinct_k{k}", 
        f"crashes_k{k}", f"same_text_k{k}"
    ] for k in range(1, K_MAX + 1)},
}
FEATURES = [c for cols in GROUPS.values() for c in cols]


# read a .jsonl file into a list, in idx order
def load_jsonl(path):
    with open(path) as f:
        rows = [json.loads(line) for line in f if line.strip()]

    return sorted(rows, key=lambda r: r["idx"])


# lowercase, keep only letters and digits, so names and questions compare as plain words
def words(text):
    return " " + " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split()) + " "


# table and column names of one database, read-only
def schema(db_path):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        columns = [r[1] for t in tables for r in con.execute(f'PRAGMA table_info("{t}")')]
    finally:
        con.close()

    return tables, columns


# how many distinct names (3+ characters) appear as whole words in the question
def mentions(question_words, names):
    found = {words(n) for n in names}
    return sum(len(n.strip()) >= 3 and n in question_words for n in found)


# shape of one SQL query: joins, nested selects, length
def sql_shape(sql):
    return {
        "sql_joins": len(re.findall(r"\bJOIN\b", sql, flags=re.I)),
        "sql_subqueries": max(0, len(re.findall(r"\bSELECT\b", sql, flags=re.I)) - 1),
        "sql_chars": len(sql),
    }


# mean and lowest token log-probability, and how many tokens were under 50% sure
def confidence(logprobs):
    values = [lp for _, lp in logprobs]
    if not values:
        return {"lp_mean": 0.0, "lp_min": 0.0, "lp_low_count": 0}

    return {
        "lp_mean": round(sum(values) / len(values), 5),
        "lp_min": min(values),
        "lp_low_count": sum(v < math.log(0.5) for v in values),
    }


# agreement among the first k samples, compared with the temperature-0 answer
def agreement(checked, sqls, ref_sql, k):
    first = checked[:k]
    crashes = sum(s["status"] != "ok" for s in first)
    ref_text = " ".join(ref_sql.split())

    return {
        f"agree_k{k}": sum(s["same_as_ref"] for s in first),
        f"distinct_k{k}": len({s["group"] for s in first if s["group"] is not None}) + crashes,
        f"crashes_k{k}": crashes,
        f"same_text_k{k}": sum(" ".join(sql.split()) == ref_text for sql in sqls[:k]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True, help="the question file the runs were made from")
    ap.add_argument("--db_root", required=True, help="folder holding <db_id>/<db_id>.sqlite")
    ap.add_argument("--runs", required=True, help="start of the run file names, e.g. outputs/train or outputs/minidev")
    ap.add_argument("--out", required=True, help="CSV to write")
    args = ap.parse_args()

    with open(args.questions) as f:
        questions = json.load(f)

    runs = {
        "small": load_jsonl(f"{args.runs}_qwen7b.jsonl"),
        "small_check": load_jsonl(f"{args.runs}_qwen7b_check.jsonl"),
        "small_lp": load_jsonl(f"{args.runs}_qwen7b_lp.jsonl"),
        "samples": load_jsonl(f"{args.runs}_qwen7b_s5.jsonl"),
        "samples_check": load_jsonl(f"{args.runs}_qwen7b_s5_vs_t0_check.jsonl"),
        "large_check": load_jsonl(f"{args.runs}_qwen32b_check.jsonl"),
    }
    for name, rows in runs.items():
        assert len(rows) == len(questions), f"{name} has {len(rows)} rows, expected {len(questions)}"

    schemas = {}
    out_rows = []
    for idx, q in enumerate(questions):
        small, small_check, small_lp, samples, samples_check, large_check = (runs[n][idx] for n in runs)
        for name in runs:
            assert runs[name][idx]["question_id"] == q["question_id"], f"question {idx} doesn't match {name}"

        answer = small["samples"][0]
        assert small_lp["samples"][0]["sql"] == answer["sql"], f"question {idx}: the _lp reply differs from the main answer"
        assert len(samples_check["samples"]) == K_MAX, f"question {idx} doesn't have {K_MAX} samples"

        if q["db_id"] not in schemas:
            schemas[q["db_id"]] = schema(f"{args.db_root.rstrip('/')}/{q['db_id']}/{q['db_id']}.sqlite")
        tables, columns = schemas[q["db_id"]]

        question, hint = q["question"], q.get("evidence") or ""
        q_words = words(question)
        result = small_check["samples"][0]
        crashed = int(result["status"] != "ok")

        row = {
            "idx": idx,
            "question_id": q["question_id"],
            "db_id": q["db_id"],
            "difficulty": q["difficulty"],
            "q_words": len(question.split()),
            "q_has_number": int(bool(re.search(r"\d", question))),
            **{name: int(bool(re.search(pattern, question, flags=re.I))) for name, pattern in KEYWORDS.items()},
            "has_hint": int(bool(hint.strip())),
            "hint_words": len(hint.split()),
            "db_tables": len(tables),
            "db_columns": len(columns),
            "q_table_mentions": mentions(q_words, tables),
            "q_column_mentions": mentions(q_words, columns),
            "sql_crashed": crashed,
            "sql_empty": int(not crashed and result["rows"] == 0),
            "sql_rows": 0 if crashed else result["rows"],
            **sql_shape(answer["sql"]),
            "reply_tokens": answer["output_tokens"],
            **confidence(small_lp["samples"][0]["logprobs"]),
        }
        sqls = [s["sql"] for s in samples["samples"]]
        for k in range(1, K_MAX + 1):
            row.update(agreement(samples_check["samples"], sqls, answer["sql"], k))

        wrong = 1 - result["correct"]
        row["label_a"] = wrong
        row["label_b"] = wrong * large_check["samples"][0]["correct"]
        out_rows.append(row)

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ID_COLUMNS + FEATURES + LABELS)
        writer.writeheader()
        writer.writerows(out_rows)

    empty = sum(row[c] is None for row in out_rows for c in FEATURES + LABELS)
    print(f"saved {len(out_rows)} rows and {len(FEATURES)} features to {args.out}")
    print(f"label_a = 1: {sum(r['label_a'] for r in out_rows)}, label_b = 1: {sum(r['label_b'] for r in out_rows)}, empty cells: {empty}")


if __name__ == "__main__":
    main()
