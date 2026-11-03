import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tqdm import tqdm

from generate import ask, build_prompt, load_questions

TRIES = 5
TRY_TEMPERATURE = 0.7
PASSES = ["together_1", "together_3", "together_5", "sequential", "large"]
WARMUP = "Reply with the word OK."
CHECK = "Write the numbers from 1 to 200, separated by commas."


# what the timing file keeps from one call (no raw reply or log-probabilities)
def record(kind, seed, sample):
    return {
        "kind": kind,
        "seed": seed,
        **{k: sample[k] for k in ["seconds", "prompt_tokens", "output_tokens", "done_reason", "sql"]},
    }


# the 7B's temperature-0 answer (with log-probabilities, as the router asks for them)
def answer(model, prompt, args):
    return record("answer", 0, ask(model, prompt, 0.0, 0, args.num_ctx, args.max_tokens, logprobs=True))


# extra try s at temperature 0.7, seed s, as in the saved 5-try runs
def extra(model, prompt, s, args):
    return record("try", s, ask(model, prompt, TRY_TEMPERATURE, s, args.num_ctx, args.max_tokens))


# the answer and all tries one after another
def sequential(prompt, args):
    return [answer(args.small, prompt, args), *(extra(args.small, prompt, s, args) for s in range(TRIES))]


# the answer and k tries sent at the same time
def together(prompt, k, args, pool):
    jobs = [pool.submit(answer, args.small, prompt, args)]
    jobs += [pool.submit(extra, args.small, prompt, s, args) for s in range(k)]
    return [j.result() for j in jobs]


# the 32B's temperature-0 answer, as in the saved baseline run
def large(prompt, args):
    return [record("answer", 0, ask(args.large, prompt, 0.0, 0, args.num_ctx, args.max_tokens))]


# untimed call so the first question doesn't pay for loading the model
def warm_up(model, args):
    ask(model, WARMUP, 0.0, 0, args.num_ctx, 4)


# stop if the server answers requests one at a time
# together passes need parallel
def check_parallel(args, pool):
    start = time.perf_counter()
    ask(args.small, CHECK, 0.0, 0, args.num_ctx, 128)
    alone = time.perf_counter() - start

    start = time.perf_counter()
    jobs = [pool.submit(ask, args.small, CHECK, 0.0, 0, args.num_ctx, 128) for _ in range(TRIES + 1)]
    for j in jobs:
        j.result()
    both = time.perf_counter() - start

    print(f"parallel check: 1 request {alone:.2f} s, {TRIES + 1} at once {both:.2f} s")
    assert both < 0.6 * (TRIES + 1) * alone, ("the server seems to answer one request at a time; restart it with OLLAMA_NUM_PARALLEL=6 ollama serve")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True, help="mini_dev_sqlite.json")
    ap.add_argument("--db_root", required=True, help="folder holding <db_id>/<db_id>.sqlite")
    ap.add_argument("--small", default="qwen2.5-coder:7b")
    ap.add_argument("--large", default="qwen2.5-coder:32b")
    ap.add_argument("--passes", default="together_1,together_3,together_5", help=f"comma-separated, run in order: {', '.join(PASSES)}")
    ap.add_argument("--out", required=True, help="timing file (.jsonl), resumed if it exists")
    ap.add_argument("--num_ctx", type=int, default=16384)
    ap.add_argument("--max_tokens", type=int, default=1024)
    ap.add_argument("--limit", type=int, default=None, help="only time the first N questions (for testing)")
    args = ap.parse_args()

    passes = args.passes.split(",")
    assert all(p in PASSES for p in passes), f"unknown pass in {passes}"
    questions = load_questions(args.questions)[: args.limit]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    done = set()
    if out.exists():
        with open(out) as f:
            done = {(r["pass"], r["idx"]) for r in map(json.loads, f)}

    with ThreadPoolExecutor(max_workers=TRIES + 1) as pool, open(out, "a") as f:
        for name in passes:
            todo = [i for i in range(len(questions)) if (name, i) not in done]
            if not todo:
                print(f"{name}: already done")
                continue

            warm_up(args.large if name == "large" else args.small, args)
            if name.startswith("together"):
                check_parallel(args, pool)

            for idx in tqdm(todo, desc=name):
                q = questions[idx]
                prompt = build_prompt(q, args.db_root)
                start = time.perf_counter()
                if name == "sequential":
                    calls = sequential(prompt, args)
                elif name == "large":
                    calls = large(prompt, args)
                else:
                    calls = together(prompt, int(name.split("_")[1]), args, pool)

                f.write(json.dumps({
                    "pass": name,
                    "idx": idx,
                    "question_id": q.get("question_id"),
                    "db_id": q["db_id"],
                    "seconds": round(time.perf_counter() - start, 3),
                    "calls": calls,
                }) + "\n")
                f.flush()

    print(f"saved {out}")


if __name__ == "__main__":
    main()
