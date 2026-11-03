import argparse
import json
import re
import sys
import time
from pathlib import Path

import ollama
from tqdm import tqdm

sys.path.append(str(Path(__file__).resolve().parent.parent / "mini_dev" / "llm" / "src"))
from prompt import generate_combined_prompts_one  # noqa: E402

SEP = "\t----- bird -----\t"

#read a BIRD question file
#has to be either JSON list or JSONL
def load_questions(path):
    with open(path) as f:
        if path.endswith(".jsonl"):
            return [json.loads(line) for line in f if line.strip()]

        return json.load(f)


#Pull one SQL line out of model's reply
def clean_sql(text):
    fence = re.search(r"`{3}(?:sql)?\s*(.*?)`{3}", text, flags=re.S | re.I)
    if fence:
        text = fence.group(1)
        
    start = re.search(r"^\s*(SELECT|WITH)\b", text, flags=re.I | re.M)
    if not start:
        start = re.search(r"\b(SELECT|WITH)\b", text)
        
    if start:
        text = text[start.start():]
        
    sql = text.split(";")[0]
    return re.sub(r"\s*\n\s*", " ", sql).strip()


# the official Mini-Dev prompt for one question, schema read from its own database
def build_prompt(q, db_root, evidence=True):
    db_path = f"{db_root.rstrip('/')}/{q['db_id']}/{q['db_id']}.sqlite"
    return generate_combined_prompts_one(
        db_path=db_path,
        question=q["question"],
        sql_dialect="SQLite",
        knowledge=q.get("evidence") if evidence else None,
    )


# one chat call to Ollama; returns the sample record saved in the cache
def ask(model, prompt, temperature, seed, num_ctx=16384, max_tokens=1024, logprobs=False):
    start = time.time()
    resp = ollama.chat(
        model=model,
        messages=[{
            "role": "user",
            "content": prompt
        }],
        options={
            "temperature": temperature,
            "num_ctx": num_ctx,
            "num_predict": max_tokens,
            "seed": seed,
        },
        logprobs=logprobs or None,
    )

    reply = resp["message"]["content"]
    sample = {
        "raw": reply,
        "sql": clean_sql(reply),
        "seconds": round(time.time() - start, 2),
        "prompt_tokens": resp.get("prompt_eval_count") or 0,
        "output_tokens": resp.get("eval_count"),
        "done_reason": resp.get("done_reason"),
    }
    if logprobs:
        sample["logprobs"] = [[t.token, round(t.logprob, 5)] for t in resp.get("logprobs") or []]

    return sample


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True, help="mini_dev_sqlite.json or dev.json")
    ap.add_argument("--db_root", required=True, help="folder holding <db_id>/<db_id>.sqlite")
    ap.add_argument("--model", default="qwen2.5-coder:7b")
    ap.add_argument("--out", required=True, help="output path without extension")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--num_ctx", type=int, default=16384, help="context window; Ollama's default 4096 cuts off big schemas")
    ap.add_argument("--max_tokens", type=int, default=1024, help="cap on reply length; stops replies that loop forever")
    ap.add_argument("--limit", type=int, default=None, help="only run the first N questions (for testing)")
    ap.add_argument("--no_evidence", action="store_true", help="leave out BIRD's evidence hints")
    ap.add_argument("--logprobs", action="store_true", help="also save each reply token's log-probability")
    args = ap.parse_args()

    questions = load_questions(args.questions)[: args.limit]
    cache_path = Path(args.out + ".jsonl")
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    done = {}
    if cache_path.exists():
        with open(cache_path) as f:
            for line in f:
                row = json.loads(line)
                done[row["idx"]] = row

    with open(cache_path, "a") as cache:
        for idx, q in enumerate(tqdm(questions)):
            if idx in done:
                continue
            
            prompt = build_prompt(q, args.db_root, evidence=not args.no_evidence)

            samples = []
            for s in range(args.samples):
                sample = ask(args.model, prompt, args.temperature, s, args.num_ctx, args.max_tokens, args.logprobs)
                if sample["prompt_tokens"] >= 0.95 * args.num_ctx:
                    print(f"\nwarning: question {idx} may be cut off, raise --num_ctx")

                samples.append(sample)
                
            row = {
                "idx": idx,
                "question_id": q.get("question_id"),
                "db_id": q["db_id"],
                "difficulty": q.get("difficulty"),
                "model": args.model,
                "samples": samples,
            }
            cache.write(json.dumps(row) + "\n")
            cache.flush()
            done[idx] = row

    preds = {str(i): done[i]["samples"][0]["sql"] + SEP + done[i]["db_id"] for i in sorted(done)}
    with open(args.out + ".json", "w") as f:
        json.dump(preds, f, indent=2)
    print(f"saved {len(preds)} predictions to {args.out}.json")


if __name__ == "__main__":
    main()
