# Project journal

A running log of the project's runs, results, findings and method decisions, with exact numbers. Newest entry at the bottom. Each entry: what was run, what came out of it, findings, and what changed in the method because of them.

---

## 2026-10-05: Repo, environment and data setup

### Hardware

- My laptop is an Apple M5 Max with 64 GB (Ollama sees 51.8 GB of GPU memory), so it can run the 32B model. Large-model runs happen here.

### Environment

- `mini_dev/` is cloned at commit `abd11b6` (2026-09-05).
- `.venv` uses Python 3.11.15, and all of `requirements.txt` installs and imports.
- Ollama 0.35.1, installed with Homebrew, serves the models locally.
- Models pulled:

| Model | Ollama ID | Size |
| --- | --- | --- |
| `qwen2.5-coder:1.5b` | `d7372fd82851` | 986 MB |
| `qwen2.5-coder:7b` | `dae161e27b0e` | 4.7 GB |
| `qwen2.5-coder:32b` | `b92d6a0bd47e` | 19 GB |

### Data downloads

| Source | File | Notes |
| --- | --- | --- |
| BIRD site | `dev.zip` (346 MB) | Folder `dev_20240627`: `dev.json`, `dev_databases.zip` |
| Mini-Dev Google Drive package | `minidev_0703.zip` (800 MB) | Question files dated 2025-07-02. I extracted only `minidev/MINIDEV/`; the rest is about 2 GB of MySQL/PostgreSQL dumps. |
| Hugging Face `birdsql/bird_mini_dev` | `mini_dev_sqlite-00000-of-00001.json` | Last modified 2026-01-18. The Mini-Dev README calls this the canonical version. |

Both zips download directly with curl (the Drive link works with `&confirm=t`), so no browser is needed.

### Finding: the Drive package's gold SQL file is broken

- `mini_dev_sqlite_gold.sql` matches its own `mini_dev_sqlite.json` on only 494 of 500 lines.
  - Question IDs 129, 137 and 138 have their gold SQL rotated, so each is scored against another question's answer.
  - Question IDs 1322, 119 and 120 have an extra db name stuck on the end of the line. The eval script splits each line on a tab and expects exactly two parts, so these lines break it.
- Hugging Face vs the Drive JSON: same 500 questions in the same order. Only one SQL differs: question ID 879 now sorts by `CAST(fastestLapSpeed AS REAL)` instead of sorting as text.
- **Change:** I added `scripts/rebuild_gold.py`, which downloads the Hugging Face JSON and rewrites `mini_dev_sqlite.json` and `mini_dev_sqlite_gold.sql` from it, in the same order.

### Finding: Mini-Dev and full dev do not share the same databases

Both downloads include the same 11 databases by name, but not the same files. Six of the 11 are byte-identical; five have the same schema but different rows:

| Database | Difference (Mini-Dev vs dev) |
| --- | --- |
| california_schools | `satscores`: same row count (2,269), different values |
| european_football_2 | `Player`: same row count (11,060), different values |
| formula_1 | fewer rows in 5 tables, e.g. `races` 954 vs 976, `lapTimes` 400,524 vs 420,369 |
| thrombosis_prediction | `Examination` 106 vs 806 rows |
| toxicology | `atom` 9,111 vs 12,333; `bond` 9,156 vs 12,379; `connected` 18,312 vs 24,758 |

Running each gold query on both versions:

- Mini-Dev (Hugging Face SQL): 237 questions use these 5 databases, and 23 return different results across the two versions.
- Full dev (`dev.json`): 700 questions use these 5 databases, and 82 return different results. 5 gold queries return nothing on the Mini-Dev copies but work on the dev copies.

**Change:** each question set uses its own databases. Mini-Dev questions use `data/minidev/dev_databases/`; `dev.json` questions use `data/dev/dev_databases/`.

### Finding: Mini-Dev questions map to dev by `question_id`

- All 500 Mini-Dev `question_id`s exist in `dev.json`, whose IDs run 0 to 1533, with the same `db_id`.
- Compared with `dev.json`, 4 Mini-Dev questions were reworded, 6 have different evidence and 16 have different gold SQL.
- **Change:** split train/test by `question_id`, not by question text (matching on text would miss 4). The training pool is the remaining 1,034 questions.

### Final data layout

```text
data/minidev/dev_databases/   11 DBs from the Drive package
data/minidev/mini_dev_sqlite.json, mini_dev_sqlite_gold.sql   rebuilt from Hugging Face
data/minidev/mini_dev_sqlite.jsonl   written by gold_check.py
data/dev/dev_databases/       11 DBs from dev.zip
data/dev/dev.json, dev.sql, dev_tables.json, dev_tied_append.json
data/_downloads/              original zips (can be deleted)
```

### Gold check

| `--meta_time_out` | Simple | Moderate | Challenging | Total | Wall time |
| --- | --- | --- | --- | --- | --- |
| 30 s (official) | 100.00 | 99.60 | 99.02 | 99.60 | |
| 400 s | 100.00 | 100.00 | 100.00 | 100.00 | about 6 min 46 s |

- The two failures at 30 s are timeouts. The time limit covers running both the predicted and the gold SQL. Gold for question ID 701 (codebase_community) takes about 103 s alone and question ID 518 (card_games) about 21 s, so at 30 s any prediction for them scores 0.
- **Change:** I use 400 s for our own scoring, and 30 s only when matching the published baselines exactly.
- Idea: a per-question checker could cache gold results once, instead of re-running question 701 on every scoring run.

### Smoke test (7B, 5 questions)

- 3 of 5 correct (quick set comparison against gold, not the official scorer).
- About 2.6 s per question; prompts about 400 tokens; 100% GPU; context window 16,384.
- Replies are bare SQL with no code fences, and `clean_sql` extracts it correctly.
- Ollama 0.35.1 picks its default context window from GPU memory (262,144 on this machine), not a fixed 4,096. `generate.py` sets 16,384 explicitly, so runs stay consistent across laptops.

### Noted for later (not done)

- The `generate.py` cache is keyed only by question position, not by model, temperature or sample count, so reusing an `--out` silently skips questions.
- At temperature 0.7, the first of the 5 samples (the one saved as the prediction) is a random sample, not the default temperature-0 answer. I'm thinking of adding a temperature-0 answer to route, and using the 5 samples only for agreement features.
- The 32B model only needs to run on the 500 Mini-Dev questions, because the classifier learns from the small model's mistakes.
- Run the 5-sample generation per split, each with its own databases, so Mini-Dev features come from the Mini-Dev databases.

### Next

- Full Mini-Dev zero-shot runs with 1.5B, 7B and 32B, scored at 400 s, split by difficulty.
- Pick the small model (closest to 50% EX) and decide on the large model.

### Baseline runs started (1.5B first)

- I'm running the six commands (generate, then score, for each model) by hand in my own terminal, with `ollama serve` in a separate tab.
- **Finding: the 1.5B model can loop forever.** On question_id 1481 (index 6, challenging) it wrote an explanation, then `T65.Segment AS Segment64, T66.Segment AS Segment65, ...` without stopping. `generate.py` had no reply length limit, and Ollama 0.35.1 runs with context shift on, so when the reply filled the 16k window it kept going. The first two attempts sat on this question until I stopped them.
- **Change:** `generate.py` now caps replies with `--max_tokens` (default 1024, sent to Ollama as `num_predict`). Each sample also saves `done_reason`: `"stop"` means it finished normally, `"length"` means it hit the cap. With the cap, question 1481 ends after 5.17 s. The 6 answers saved before the change finished well under the cap, so they're unaffected (their `done_reason` is empty).
- After 115 of 500 questions: about 2.6 s per question, and 3 replies hit the cap.
- The 1.5B writes 290 to 410 tokens per reply (explanations around the SQL) compared with about 50 for 7B, even though the prompt asks for SQL only. `clean_sql` still extracts the SQL.
- Idea: replies that hit the cap are almost always wrong, so a "hit the cap" flag could be a useful classifier feature.

### Result: 1.5B on Mini-Dev (E1)

| Model | Simple | Moderate | Challenging | Total EX |
| --- | --- | --- | --- | --- |
| qwen2.5-coder:1.5b | 29.73 | 15.20 | 6.86 | **17.80** |

- Scored with the official script at `--meta_time_out 400` (the gold check gives 100.00 at this setting). Log: `outputs/eval_minidev_qwen1.5b.txt`.
- Generation: 500/500 answers, 2.55 s per question (21.3 min of model time), prompts averaging 1,014 tokens (max 2,235, far under the 16,384 window), replies averaging 330 tokens. 3 replies hit the 1,024-token cap, 491 finished normally, and 6 were saved before `done_reason` existed. No empty SQL.
- Scoring took about 6 minutes.
- Takeaway: 17.8% is far from the roughly 50% we want for the small model (82% of answers are wrong, so the classes would be very unbalanced). The 7B is the likely small model. Accuracy falls steeply with BIRD difficulty (30 to 15 to 7), so the difficulty-label router will be a meaningful baseline.
- For reference, the Mini-Dev README's SQLite baseline for llama3-8b-instruct is 24.40 (scored at 30 s).

---

## 2026-10-06: Baselines continued

### Result: 7B on Mini-Dev (E1)

| Model | Simple | Moderate | Challenging | Total EX |
| --- | --- | --- | --- | --- |
| qwen2.5-coder:1.5b | 29.73 | 15.20 | 6.86 | 17.80 |
| qwen2.5-coder:7b | 66.22 | 47.20 | 32.35 | **49.80** |

- Scored with the official script at `--meta_time_out 400`. Log: `outputs/eval_minidev_qwen7b.txt`.
- Generation: 500/500 answers in 8 min 13 s (0.99 s per question). Every reply finished normally (`stop`) and none hit the 1,024-token cap. Replies averaged 56 tokens (median 54, max 592). Prompts were the same as for the 1.5B (average 1,014 tokens, max 2,235). No empty SQL.
- Scoring took under 3 minutes, compared with about 6 for the 1.5B.
- The 7B is 2.6 times faster per question than the 1.5B despite being bigger, because it replies with bare SQL (56 tokens) while the 1.5B adds explanations (330 tokens).
- For reference: the Mini-Dev README lists SQLite EX of 47.80 for gpt-4 and 45.80 for gpt-4-turbo. Those were scored at 30 s against the older gold file, so the comparison is rough, but a local 7B is already at GPT-4's published level. The README's "Qwen2.5 Coder 7B: 12.22" is for LiveSQLBench, a different benchmark, not Mini-Dev.

### Decision: the 7B is the small model

- The rule set beforehand was to pick whichever small model is closest to 50% EX. The 7B gets 49.80 (249 right, 251 wrong), so the classifier gets an almost even split of right and wrong examples. The 1.5B's 17.80 would mean 82% wrong.
- **Change:** the training data generation (5 samples per dev question) uses only the 7B. The 1.5B stays as a row in the E1 table, and I won't run it again.
- The "always small" end of the routing curve is 49.80.
- Accuracy still falls with difficulty (66 to 47 to 32), so the difficulty-label router stays a real baseline. But the 7B gets a third of the challenging questions right and misses a third of the simple ones, so difficulty alone won't separate right answers from wrong ones well. That leaves room for our classifier to win.
- New time estimate for the training data: 1,534 questions times 5 samples is about 7,700 calls. At about 1 s per call that's roughly 2 to 3 hours, not overnight. Replies at temperature 0.7 may be a little longer.

### Next

- Generate and score the 32B. That gives the top of the routing curve and the gap a router can recover.
- Then decide on the large model. If the 32B scores only a little above 49.80, consider an API model instead.

### Finding: all three models are 4-bit versions

- Checked with `ollama show`: all three models are `Q4_K_M` quantized with a 32,768-token maximum context. Our scores are for these compressed versions.

### Result: 32B on Mini-Dev (E1), baselines complete

| Model | Simple | Moderate | Challenging | Total EX |
| --- | --- | --- | --- | --- |
| qwen2.5-coder:1.5b | 29.73 | 15.20 | 6.86 | 17.80 |
| qwen2.5-coder:7b | 66.22 | 47.20 | 32.35 | 49.80 |
| qwen2.5-coder:32b | 72.30 | 54.80 | 44.12 | **57.80** |

- Scored with the official script at `--meta_time_out 400`. Log: `outputs/eval_minidev_qwen32b.txt`.
- Generation: 500/500 answers in 34 min 33 s (4.15 s per question, 4.2 times slower than the 7B). Every reply finished normally (`stop`), and none hit the cap. Replies averaged 59 tokens (median 56, max 513); the slowest question took 22 s. No empty SQL. Scoring took about 7 minutes.
- While loaded, the 32B uses about 23 GB of GPU memory (`ollama ps`), running 100% on the GPU.
- The 32B beats the 7B by 8.0 points overall, and by the most on challenging questions (+11.8).

### Finding: question-by-question, 7B vs 32B

The official scorer prints only totals, so I wrote a quick per-question checker (scratch script, not in the repo yet). It uses the same set comparison and the same 400 s shared limit, opens the databases read-only, and reproduces the official totals exactly for all three models (17.80, 49.80, 57.80).

| | 32B right | 32B wrong |
| --- | --- | --- |
| **7B right** | 219 | 30 |
| **7B wrong** | 70 | 181 |

- The 32B fixes only 70 of the 7B's 251 wrong answers (27.9%). For the other 181, escalating costs a 32B call and gains nothing.
- On 30 questions the 7B is right and the 32B is wrong, so escalating them would hurt.
- **Oracle router: 63.8%.** Escalating exactly the 70 questions the 32B fixes (14% of questions) beats always using the 32B (57.8%) by 6 points. A router can in principle beat the large model alone, not just match it more cheaply.
- Using all three models, the oracle is 65.4%. The 1.5B adds only 8 questions neither other model gets.
- Headroom by difficulty (7B, then 32B, then oracle): simple 66.2 / 72.3 / 77.0, moderate 47.2 / 54.8 / 60.8, challenging 32.4 / 44.1 / 52.0.
- **Difficulty-label router:** escalating the 102 challenging questions (20.4%) gives 52.2%. A random router at the same 20.4% expects 51.4% (49.8 + 0.204 × 8.0). So the difficulty label helps a little; our classifier has to beat 52.2% at 20.4% escalation.

### Large model: leaning towards keeping the 32B (not decided yet)

- The gap is 8.0 points, and an oracle shows 14 points of headroom (49.8 to 63.8), enough for a meaningful routing curve.
- It's free and local, and its timings (4.15 s against 0.99 s per question) give the cost experiment a clear cost ratio.
- For comparison, the Mini-Dev README's plain-prompt API baselines are lower (gpt-4 47.80, gpt-4-turbo 45.80, scored at 30 s against the older gold file). A newer API model might score higher, but that's untested and would cost money. It could be a stretch comparison.
- Catch: the 32B fixes only about 28% of the 7B's wrong answers, so "the 7B is probably wrong" doesn't mean "the 32B will fix it". That's fine for the plan: escalating a question both get wrong costs a call but never lowers accuracy.

### Next

- Decide on the large model (leaning 32B).
- Add the per-question checker to `scripts/`. The classifier's training labels need it, and it can cache gold results instead of re-running question 701 every time.
- Training data: the 7B, 5 samples per question, on the dev questions against the dev databases, and on the Mini-Dev questions against the Mini-Dev databases (about 2 to 3 hours in total).

### Plan changes

- Run stage 3 on a training file of the 1,034 non-Mini-Dev questions instead of all 1,534.
- Add a temperature-0 7B run for the training questions, so labels and SQL features come from the answer the router would keep.
- Run 5 samples on Mini-Dev against its own databases. The new estimate is about 8,700 calls, roughly 2.5 to 3 hours.
- Optionally also predict "worth escalating" (7B wrong and 32B right), which needs a 32B run on the training questions (about 70 minutes).
- Before the full 5-sample runs, a 50-question pilot to check that the samples sometimes disagree, since the agreement feature depends on it.

### Decision: the 32B is the large model

- The only other option was a paid API model, and nothing points to paying for one. The 32B is free and local, scores 57.80 (8.0 points above the 7B), and leaves 14 points between "always small" and the oracle (49.8 to 63.8). Its answers for all 500 test questions are already saved, so routing needs no more large-model runs. The Mini-Dev README's published API baselines with this kind of prompt are lower anyway (gpt-4 47.80).
- An API model stays only a possible stretch comparison.

### Decision: train two classifier versions (A and B)

- **A, the main result:** "Is the 7B's answer wrong?" 50% "yes" on the test set (251 of 500), and the labels need only 7B runs.
- **B, the comparison:** "Is this question worth sending to the 32B?" (the 7B is wrong and the 32B is right). 14% "yes" on the test set (70 of 500).
- Why compare: a perfect A at 14% escalation reaches only 53.7% (just 28% of the 7B's wrong answers are fixable), while a perfect B reaches 63.8%. At 50% escalation both reach 63.8%. So B has the better curve in theory, but it learns from far fewer and subtler examples. Which one wins in practice is an empirical question.
- **Changes:**
  - Stage 3 adds a 32B run on the 1,034 training questions (temperature 0, dev databases, about 70 minutes), used only for B's labels, never as a feature.
  - Stages 5 and 6 train, ablate and draw routing curves for both versions, plus a direct A vs B comparison at equal escalation.

### Made: the training file (`scripts/make_train.py`)

- `python scripts/make_train.py data/dev/dev.json data/minidev/mini_dev_sqlite.json data/dev/train.json` copies `dev.json` without the 500 Mini-Dev questions, matched by `question_id`. Result: 1,034 questions, 0 overlap with the test set.
- It runs no model; it only makes the question file `generate.py` reads. Without it, `generate.py` on `dev.json` would also answer the 500 test questions (about 2,500 wasted calls at 5 samples), and they could slip into training. The baselines didn't need it because the test questions already come as their own file.

### Finding: the training questions are much easier than the test questions

| | Simple | Moderate | Challenging |
| --- | --- | --- | --- |
| Training (1,034) | 777 (75%) | 214 (21%) | 43 (4%) |
| Test (500) | 148 (30%) | 250 (50%) | 102 (20%) |

- Mini-Dev was picked to have more hard questions, so the leftovers are mostly easy. The 7B will be wrong on fewer than half the training questions, and the classifier sees few hard examples.
- It doesn't break the plan: the routing curve uses escalation shares (20%, 30%, 50%), not a fixed probability cutoff.

### Made: the per-question checker (`scripts/check.py`)

- Reads a `generate.py` cache (`.jsonl`) and its question file, runs each gold query once, then runs every sample against it, with the same rule (same set of rows) and the same shared 400 s limit as the official scorer. Writes `<cache>_check.jsonl`: per sample, right or wrong, `ok`/`error`/`timeout`, row count, and a `group` number (same group = same rows, for self-agreement). Prints EX by difficulty, and how often the samples all agree.
- Why not just the official scorer: it only prints totals, reads only sample 0 from the `.json`, and needs Mini-Dev's file formats. The classifier needs per-question labels, all 5 samples and their agreement, and it has to work on the training questions. EX numbers we report still come from the official scorer.
- The baselines didn't need it because stage 1 only needed totals. The 7B vs 32B comparison used a quick early version of it.
- **Check against the official scorer** on the saved test answers (all three runs took about 8 minutes):

  | Model | Simple | Moderate | Challenging | Total |
  | --- | --- | --- | --- | --- |
  | 1.5B | 29.73 | 15.20 | 6.86 | 17.80 |
  | 7B | 66.22 | 47.20 | 32.35 | 49.80 |
  | 32B | 72.30 | 54.80 | 44.12 | 57.80 |

  Identical to the official scorer for all three. Question by question, it also agrees with the quick early version on all 1,500 answers. Every gold query ran fine.
- **Finding: how often the SQL crashes** (doesn't run at all) on the test questions: 1.5B 277 of 500 (55%), 7B 57 (11.4%), 32B 17 (3.4%). A crash is always wrong, so "crashed" will be an easy feature, but it covers only about a fifth of the 7B's 251 wrong answers; the rest run and return the wrong rows.
- The test-set results are saved as `outputs/minidev_qwen{1.5b,7b,32b}_check.jsonl`, which the routing stage will use.

### Result: 5-sample pilot (7B, first 50 training questions)

- Command: `generate.py` on `data/dev/train.json` with `--samples 5 --temperature 0.7 --out outputs/train_qwen7b_s5 --limit 50`, then `check.py` on it. 2 min 56 s (3.53 s per question, 0.71 s per try); all 250 tries ended with `stop`.
- **The tries disagree enough:** all 5 gave the same result on only 21 of 50 questions (42%), with 2.22 different results per question on average. That's well under the 45 of 50 cutoff, so temperature 0.7 stays and the full run continues from question 50 under the same `--out`.
- **Score:** 36.00 for the first try (simple 40.00 on 40, moderate 20.00 on 10). Low because `train.json` is in database order and all 50 are california_schools, the 7B's hardest database (23% right on its 30 test questions, against 75% for superhero). Not a bug: every gold query ran fine. The 5 tries score 36, 42, 38, 42 and 44%; at least one of the 5 is right on 28 of 50.
- **Early hint that agreement works** (50 questions from one database, so only a hint): how many of the 5 tries match the first try's result, against how often the first try was right:

  | Tries matching the first (incl. itself) | Questions | First try right |
  | --- | --- | --- |
  | 0 (first try crashed) | 11 | 0 |
  | 1 | 3 | 0 |
  | 2 | 4 | 2 |
  | 3 | 3 | 1 |
  | 4 | 8 | 4 |
  | 5 | 21 | 11 |

  When the first try crashed or nothing else matched it, it was never right (0 of 14). When 4 or 5 tries agreed, it was right half the time (15 of 29).
- **Noted for features:** the 7B's test score swings a lot by database (23% to 75%). Whether to use the database as a feature is a call for the features stage; it would help here because training and test share the same 11 databases, but wouldn't carry over to new databases.
- **New time estimates:** the full 5-sample training run is about 1 hour for the remaining 984 questions, and the 5-sample test run about 30 minutes. Stage 3 is about 3 hours of model time in total.

### Finding: the official scorer fails silently

Tested on a scratch folder:

- Without the trailing `/` on `--db_root_path`, the gold check gives 0.00 in every column, with no error.
- Without `--output_log_path`, it writes a file named `SQLite` in the current folder.
- It adds to its log file instead of replacing it, so re-scoring a run leaves two tables.

---

## 2026-10-09: Stage 3 runs done and checked

### Runs

All four stage 3 runs finished (6 and 7 Oct) and went through `check.py` (8 Oct):

| Run | Questions | Databases | Tries | Model time | Per question | Estimate was |
| --- | --- | --- | --- | --- | --- | --- |
| `train_qwen7b` | 1,034 training | dev | 1 at temp 0 | 12.2 min | 0.71 s | 17 min |
| `train_qwen32b` | 1,034 training | dev | 1 at temp 0 | 52.5 min | 3.05 s | 70 min |
| `train_qwen7b_s5` | 1,034 training | dev | 5 at temp 0.7 | 60.5 min (incl. the 50-question pilot) | 3.51 s | 1 hour |
| `minidev_qwen7b_s5` | 500 test | Mini-Dev | 5 at temp 0.7 | 37.9 min | 4.55 s | 30 min |

About 2 h 43 min of model time in total. The 32B is 4.3 times slower per call than the 7B on the training questions (3.05 s against 0.71 s), close to the 4.2 times on the test set.

### File checks

- Every cache has every question exactly once (1,034 or 500), and `question_id` and `db_id` match the question file at every position. Right model in every row.
- All 9,738 tries ended with `stop`; none hit the 1,024-token cap. No empty SQL. The `.json` predictions match sample 0 on every question.
- Every gold query ran (`ok`) and no answer timed out. Slowest gold: training question_id 646 at 3.3 to 6.9 s; Mini-Dev question_id 701 at 148 s with 8 checks running in parallel (about 100 s alone), still well under 400 s.
- The temperature-0 training run really is a separate run: its SQL matches the first of the 5 tries word for word on only 316 of 1,034 questions (it appears somewhere among the 5 on 830).
- The totals `check.py` printed match what I recomputed from the `_check.jsonl` files.

### Result: 7B and 32B on the training questions (temperature 0)

| Model | Simple (777) | Moderate (214) | Challenging (43) | Total |
| --- | --- | --- | --- | --- |
| qwen2.5-coder:7b | 59.07 | 39.72 | 39.53 | **54.26** (561 right) |
| qwen2.5-coder:32b | 68.98 | 49.53 | 55.81 | **64.41** (666 right) |

| | 32B right | 32B wrong |
| --- | --- | --- |
| **7B right** | 505 | 56 |
| **7B wrong** | 161 | 312 |

- **Label A** ("is the 7B wrong?"): 473 of 1,034 yes (45.7%), against 50.2% on the test set. Close to balanced.
- **Label B** ("7B wrong and 32B right"): 161 yes (15.6%), against 70 (14.0%) on the test set. So B has 161 positive training examples.
- The 32B fixes 161 of the 7B's 473 wrong answers (34.0%), against 27.9% on the test set. The gap between the models is 10.15 points (8.0 on test), and the oracle is 69.83.
- Crashes: 7B 115 of 1,034 (11.1%; test 11.4%), 32B 25 (2.4%; test 3.4%). Of the 7B's 473 wrong answers, 115 crashed and 358 ran and returned the wrong rows (78 of those returned no rows at all).
- **Finding: the training questions are only easier because of the mix.** Within each difficulty, the 7B scores lower on training than on test for simple (59.1 vs 66.2) and moderate (39.7 vs 47.2); challenging is higher (39.5 vs 32.4, but only 43 questions). I don't know why yet. One guess: Mini-Dev's questions and gold SQL were cleaned up (16 of its gold queries differ from `dev.json`) and the rest of dev wasn't. Untested.
- 7B by database on training: superhero 91% (77 questions) down to thrombosis_prediction 33% (113). california_schools, the hardest on test (23%), is 41% on training (59).

### Result: 5 tries at temperature 0.7

| | Training (1,034) | Test (500) |
| --- | --- | --- |
| First try: simple / moderate / challenging | 58.82 / 34.58 / 44.19 | 64.19 / 45.60 / 24.51 |
| First try, total | 53.19 | 46.80 |
| Average of the 5 tries | 53.37 | 47.52 |
| Temperature-0 answer (for comparison) | 54.26 | 49.80 |
| At least one of the 5 right | 65.67 (679) | 62.20 (311) |
| Majority vote of the 5 | 58.22 | 51.60 |
| All 5 gave the same result | 542 (52.4%) | 220 (44.0%) |
| Different results per question | 1.99 | 2.21 |

- Temperature 0.7 costs accuracy: the first try is 1.1 points below the temperature-0 answer on training and 3.0 on test. This backs the earlier plan: route the temperature-0 answer, use the 5 tries only for agreement.
- Majority vote (most common result among tries that ran, ties go to the earlier try) beats the temperature-0 answer by 4.0 points on training and 1.8 on test, at 5 calls per question. Not in the plan yet; it could be one more "small model only" reference point.

### Finding: agreement between the tries predicts correctness

How many of the 5 tries return the same rows as the first try, against how often the first try was right:

| Tries matching the first (incl. itself) | Training questions | First try right | Test questions | First try right |
| --- | --- | --- | --- | --- |
| 0 (first try crashed) | 138 | 0 (0%) | 76 | 0 (0%) |
| 1 | 54 | 8 (14.8%) | 42 | 9 (21.4%) |
| 2 | 83 | 21 (25.3%) | 47 | 6 (12.8%) |
| 3 | 92 | 48 (52.2%) | 49 | 18 (36.7%) |
| 4 | 125 | 58 (46.4%) | 66 | 36 (54.5%) |
| 5 | 542 | 415 (76.6%) | 220 | 165 (75.0%) |

- Used alone as a score, this count gives ROC-AUC 0.796 on training. The pilot's hint holds on the full run. (I also looked at the test number, 0.819, as a check only; feature choices must come from the training questions.)
- Catch: this is agreement with the *first try*, but the router keeps the *temperature-0 answer*. `check.py` only groups results within one run, so "how many of the 5 tries return the same rows as the temperature-0 answer" has to be computed in the features stage by running both and comparing.
- Signals for the temperature-0 answer that need no extra runs (training AUC, then test): how many of the 5 tries crashed, 0.668 / 0.656 (when all 5 crashed, the temperature-0 answer was right on 0 of 55 training questions); whether the temperature-0 SQL itself crashed, 0.622 / 0.614; how many tries wrote word-for-word the same SQL, 0.656 / 0.654.
- Consistency check between the runs (uses the gold answers, so not a feature): when all 5 tries were right, the temperature-0 answer was right on 413 of 415 training questions; when none were, on 1 of 355.

### Next

- Stage 3 is done; no more model runs are needed.
- Features stage: build the feature table, one row per question with labels A and B. First feature to add: how many of the 5 tries return the same rows as the temperature-0 answer.

### Result: dataset and reference-curve numbers

All from saved runs and the question files:

- **Databases:** 75 tables and 798 columns over the 11; from toxicology (4 tables, 11 columns) to formula_1 (13 tables) and european_football_2 (199 columns).
- **Training vs test questions:** question length 13.9 vs 15.8 words; hint length 12.2 vs 19.4 words; gold SQL with a JOIN 71% vs 81%, with a nested SELECT 6% vs 13%.
- **Reference curves on the test set** (escalation share 0 to 100%): random, perfect A (escalates only the 7B's wrong answers) and oracle. At 20 / 30 / 50%, perfect A gets 55.38 / 58.17 / 63.74; the oracle stays at 63.80 from 14% to 94%.
- **Areas under those curves (test):** random 53.80, difficulty order 54.30, perfect A 58.79, oracle 62.64.
- **Difficulty router escalating challenging + moderate:** 56.00 at 70.4% (random 55.43).
- **Licenses:** the Mini-Dev repo states CC BY-SA 4.0 only by a README badge (no LICENSE file); Hugging Face lists the dataset as CC BY-SA 4.0. Ollama is MIT.

### Finding: missing hints explain part of the training/test gap

- 146 training questions (14.1%) have no evidence hint, against 2 test questions (0.4%). On training, the 7B gets 56.1% with a hint and 43.2% without (32B: 65.5% and 57.5%). Simple questions with a hint: 62.3% (637 questions); without: 44.3% (140). Moderate questions with a hint are still at 40.2%, against 47.2% on test, so the hints don't explain all of it.

---

## 2026-10-10: Agreement, simple rules, confidence and significance

### Why

Five gaps in the method so far:

1. The 0.796 AUC is agreement with the first *sample*, not with the temperature-0 answer the router keeps.
2. No simple-rule baseline: nothing showed the classifier has to beat more than random.
3. No significance tests, on a 500-question test set.
4. The cost model makes the 5-sample router slower than always-large on one machine.
5. The 7B's token probabilities (free from the call already made) weren't used.

Numbers that use the 7B's outputs are training-set numbers; the test set is still untouched apart from the reference routers already reported.

### Made: two script options

- `generate.py --logprobs`: saves each reply token's log-probability (`logprobs`, a list of `[token, logprob]` pairs per sample).
- `check.py --ref <cache>`: also runs the reference run's sample 0 and marks each sample `same_as_ref`. Ran it on `train_qwen7b_s5` with `--ref outputs/train_qwen7b.jsonl` → `outputs/train_qwen7b_s5_vs_t0_check.jsonl` (1 min). Right/wrong labels are identical to `train_qwen7b_s5_check.jsonl`, and the reference statuses match `train_qwen7b_check.jsonl` on all 1,034.

### Result: agreement with the temperature-0 answer (training)

- ROC-AUC **0.784** for A, 0.778 for B (PR-AUC 0.765 and 0.349; base rates 0.457 and 0.156). Replaces the 0.796.
- All 5 agree: 7B right on 413 of 539 (76.6%). None agrees: 1 of 138 (115 of those are temperature-0 crashes).
- By number of samples (A): 0.701 with 1, 0.742 with 2, 0.765 with 3, 0.775 with 4, 0.784 with 5. Most of it comes from the first 2-3.

### Result: simple routers on training

- "Escalate if at most 2 of 5 samples agree": **62.96 at 25.1%**, against 56.81 for random at that share. "At most 4": 64.70 at 47.9%, above always-large (64.41).
- "Escalate if the 7B's SQL crashed": 59.67 at 11.1% (random 55.38).
- Difficulty label: 54.93 at 4.2% (random 54.68); with moderate, 56.96 at 24.9% (random 56.78).
- So the bar for the classifier is the agreement rule, not random.

### Result: token log-probabilities (training)

- New run `outputs/train_qwen7b_lp` (7B, temperature 0, `--logprobs`): 0.79 s per question (0.71 without). All 1,034 replies identical to `train_qwen7b`.
- Mean token log-probability: ROC-AUC 0.731 for A, 0.663 for B. Sum: 0.755 / 0.663 (partly length). Lowest token: 0.657 / 0.611.
- Not redundant with agreement (Spearman 0.47): among the 539 questions where all 5 samples agree, it still gives 0.658.

### Result: majority vote (training)

- 58.22 vs. 54.26 for the temperature-0 answer (fixes 62, breaks 21). Oracle with the majority answer kept: 70.60 (vs. 69.83).

### Result: significance (test, reference routers only)

- 7B vs. 32B: McNemar exact p = 7.9e-5 (70 fixed, 30 broken); 32B minus 7B +8.0, 95% CI +4.2 to +11.8.
- One system's EX on 500 questions: about ±4.4 points (7B: 45.4 to 54.2).
- **Finding: the difficulty label is not clearly better than random.** +0.77 at 20.4% (CI −0.94 to +2.51) and +0.57 at 70.4% (CI −1.06 to +2.18). Hard questions are where the 7B fails, but the 32B fails there too.

### Result: Soft F1 (test, official scorer, 400 s)

- 1.5B 19.62 (simple 31.17 / moderate 16.52 / challenging 10.47); 7B 52.68 (68.01 / 50.64 / 35.45); 32B 61.62 (74.97 / 59.32 / 47.89). Same ranking as EX, 2 to 4 points higher.
- Gold check: Soft F1 100.00 on an idle machine. **Found:** my first gold run gave 99.80 because question 701 timed out at 400 s while Ollama was generating and another 8-process job was running. The gold check runs 701's gold SQL twice (about 150 s each under load). Scorers should run on an otherwise idle machine.

### Result: SQL execution time

- Running the SQL takes 0.037 s per question for the temperature-0 answer and 0.19 s for all 5 samples (mean; medians 0). Negligible.
- With 5 samples drawn one after another, the router takes at least ~5.8 s per question on the test set, more than always-large (4.15 s). Without samples it is faster than always-large while escalating under 76%.

### Run: token log-probabilities on the test set

- `outputs/minidev_qwen7b_lp` (7B, temperature 0, `--logprobs`, 500 test questions): 7 min 11 s, 0.86 s per question. All 500 replies identical to `minidev_qwen7b`, so its right/wrong marks still apply. No reply hit the cap; every reply has log-probabilities. Nothing scored or analyzed: test-set features stay untouched until E4.

---

## 2026-10-22: Methodology for the remaining experiments

### Plan changes

- Before the single test run, rehearse all of E4 on the training set using out-of-fold cross-validation scores, then write the frozen choices (classifiers, features, tie-break, which agreement rule the classifier must beat, majority variant, bootstrap seed) here before scoring Mini-Dev.
- Tune E2's settings with nested cross-validation, so the reported CV scores aren't from the folds the settings were picked on.
- The agreement features get one set of columns per k = 1 to 5, since E3 and E5 compare numbers of tries.
- Test-set exposure so far: a few test-set numbers for the 7B's samples (agreement ROC-AUC 0.819 with the first sample, the crash and same-text AUCs, majority vote 51.6%) were computed once on 9 Oct as a check. Nothing was chosen from them.

### Run: test samples against the temperature-0 answer

- `check.py --ref` on `minidev_qwen7b_s5` with `--ref outputs/minidev_qwen7b.jsonl` → `outputs/minidev_qwen7b_s5_vs_t0_check.jsonl`. 2 min 40 s for 500 questions.
- Checks: 500 questions; the samples' right/wrong marks are identical to `minidev_qwen7b_s5_check.jsonl`, and the reference statuses match `minidev_qwen7b_check.jsonl` on all 500. The printed summary repeats the 9 Oct numbers (first sample 46.80; all 5 samples agree on 220 of 500).
- This was the last input missing for the test-set features. The `same_as_ref` marks haven't been looked at, and stay unread until E4.

### Made: the feature tables (`scripts/features.py`)

- One row per question: 4 ID columns (`idx`, `question_id`, `db_id`, `difficulty`), 46 features and 2 labels. Feature groups: question (12), schema (4), the 7B's SQL and its result (7), token confidence (3), and agreement for each k = 1 to 5 (4 columns each: agreeing with the temperature-0 answer, distinct results, crashes, identical SQL text, using only the first k samples). The feature list is fixed in the script, so `difficulty`, `db_id` and anything from the 32B can't become features.
- `outputs/features_train.csv` (1,034 rows) and `outputs/features_test.csv` (500 rows), each from its own question file, databases and runs. No empty cells: a crashed query gets `sql_rows` 0 and `sql_crashed` 1.
- **Checks on training, all matching the earlier measurements:** labels 473 (A) and 161 (B); all 5 samples agree on 539, none on 138; 1.99 distinct results per question; ROC-AUC for A of agreement with 1 to 5 samples 0.701 / 0.742 / 0.765 / 0.775 / 0.784; mean and lowest log-probability 0.731 and 0.657; the 7B's SQL crashing 0.622; samples crashing 0.668; identical SQL text 0.657 (0.656 on 9 Oct); for B, agreement 0.778 and mean log-probability 0.663; 146 questions without a hint (56.1% right with one, 43.2% without); 75 tables and 798 columns over the 11 databases.
- **Checks on test, counts only:** 500 rows, 251 for A and 70 for B (as in E1), no empty cells, same columns as training. No feature was scored against the test labels.
- **Finding (training):** every 7B answer that ran and returned no rows was wrong (78 of 78), so `sql_empty` = 1 never marks a right answer.
- Two keyword flags are rare on training: `kw_ratio` on 6 questions and `kw_difference` on 4. The others: `kw_count` 294, `kw_highest` 138, `kw_average` 58, `kw_total` 53, `kw_percent` 41, `kw_lowest` 26.

---

## 2026-10-27: E2, comparing classifier types

### Result: E2 on the training questions

`scripts/train.py --exp e2`: logistic regression (`lr`), random forest (`rf`) and gradient boosting (`gb`) on the 30 `all_k5` features (everything, with agreement from all 5 samples), with class weights. Settings picked by nested CV (3 inner folds, ROC-AUC). Outer CV: stratified 5-fold, and leave-one-database-out (LODO, 11 folds, scores pooled before measuring). Each setup over seeds 0 to 2. Numbers are means, with the std over the 3 seeds in brackets. Outputs: `outputs/e2_results.csv`, and every question's out-of-fold score in `outputs/e2_scores.csv` (37,224 rows).

| Target | Classifier | ROC-AUC, 5-fold | PR-AUC, 5-fold | ROC-AUC, LODO | PR-AUC, LODO | Precision / recall at 30%, 5-fold | Settings picked most |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | lr | **0.879** (0.003) | **0.884** (0.003) | 0.863 (0.001) | 0.871 (0.001) | 0.897 / 0.588 | C = 1 |
| A | rf | 0.873 (0.004) | 0.878 (0.002) | 0.859 (0.003) | 0.865 (0.002) | 0.902 / 0.591 | no depth limit, leaf 1 |
| A | gb | 0.877 (0.005) | 0.883 (0.003) | **0.875** (0.001) | **0.878** (0.001) | 0.901 / 0.591 | depth 2, 100 rounds |
| B | lr | 0.781 (0.003) | 0.347 (0.008) | 0.772 (0.001) | 0.343 (0.002) | 0.344 / 0.663 | C = 0.01 |
| B | rf | **0.795** (0.009) | 0.378 (0.018) | **0.784** (0.002) | 0.331 (0.001) | 0.334 / 0.644 | no depth limit, leaf 10 |
| B | gb | 0.792 (0.006) | **0.382** (0.013) | 0.777 (0.000) | **0.356** (0.000) | 0.342 / 0.658 | depth 2, 100 rounds |

### Findings

- **Target A: the classifier beats agreement alone by a wide margin.** ROC-AUC 0.873 to 0.879 against 0.784 for the agreement count by itself, and PR-AUC 0.878 to 0.884 against 0.765. The three types are within 0.006 of each other on 5-fold, about 1 to 2 seed stds, so none clearly wins.
- **Target A, flagged shares (5-fold):** at 20% the flagged questions are 98.2 to 98.9% really wrong, with recall 0.430 to 0.433 against a ceiling of 207 / 473 = 0.438. At 30%, precision 0.897 to 0.902 and recall 0.588 to 0.591 (ceiling 310 / 473 = 0.655). At 50%, precision 0.730 to 0.743 and recall 0.798 to 0.812.
- **The clues mostly carry over to unseen databases.** From 5-fold to LODO, ROC-AUC for A drops 0.016 (`lr`), 0.014 (`rf`) and 0.002 (`gb`).
- **Target B is much harder, and the classifier adds little over agreement alone.** ROC-AUC 0.781 to 0.795 against 0.778 for agreement by itself, and PR-AUC 0.347 to 0.382 against 0.349 (base rate 0.156). Logistic regression picks the strongest penalty offered (C = 0.01). The random forest's PR-AUC drops the most under LODO (0.378 to 0.331).
- **Gradient boosting always picks the simplest settings in its grid** (depth 2, 100 rounds) for both targets and both splits. Simpler settings weren't offered, so its grid may be cut off at that end.

### Result: E3, feature steps (training, 5-fold, 3 seeds)

`scripts/train.py --exp e3` with all three classifier types. Each step adds a feature group: question and schema only (`before_generation`, 16 features), then the 7B's SQL, its execution result and token confidence (`plus_answer`, 26, no extra model calls), then agreement from the first k samples (`plus_agree_k1` to `k5`, 30 each; each step is `plus_answer` plus one k's agreement columns), then database identity (`plus_agree_k5_db`, 41). ROC-AUC means over seeds 0 to 2; seed stds are 0.002 to 0.007 for A and 0.002 to 0.019 for B.

| Step | A: lr | A: rf | A: gb | B: lr | B: rf | B: gb |
| --- | --- | --- | --- | --- | --- | --- |
| `before_generation` | 0.636 | 0.679 | 0.660 | 0.559 | 0.596 | 0.594 |
| `plus_answer` | 0.861 | 0.865 | 0.862 | 0.737 | 0.764 | 0.757 |
| `plus_agree_k1` | 0.871 | 0.866 | 0.872 | 0.761 | 0.779 | 0.772 |
| `plus_agree_k2` | 0.870 | 0.866 | 0.870 | 0.763 | 0.779 | 0.770 |
| `plus_agree_k3` | 0.877 | 0.869 | 0.871 | 0.778 | 0.792 | 0.785 |
| `plus_agree_k4` | 0.879 | 0.874 | 0.874 | 0.782 | 0.801 | 0.789 |
| `plus_agree_k5` | 0.879 | 0.873 | 0.877 | 0.781 | 0.795 | 0.792 |
| `plus_agree_k5_db` | 0.881 | 0.875 | 0.878 | 0.784 | 0.794 | 0.797 |

PR-AUC for B (base rate 0.156): `before_generation` 0.176 / 0.203 / 0.206, `plus_answer` 0.333 / 0.373 / 0.358, `plus_agree_k5` 0.347 / 0.378 / 0.382, `plus_agree_k5_db` 0.355 / 0.389 / 0.404 (lr / rf / gb).

### Findings

- **Running the 7B's SQL is the big step.** For A, ROC-AUC goes from 0.636 to 0.679 with question and schema only, to 0.861 to 0.865 with the 7B's SQL, its result and its confidence, a gain of 0.19 to 0.23 with no extra model calls. For B, from 0.559 to 0.596 (PR-AUC 0.176 to 0.206, close to the 0.156 base rate) to 0.737 to 0.764. On this data, a router that decides before generation does far worse than one that runs the small model's SQL first.
- **Extra samples add little for A.** From `plus_answer` to 5 samples: +0.018 (lr), +0.008 (rf), +0.015 (gb). For lr, the first sample gives +0.010 and three give +0.017. Two samples add nothing over one for any type (differences of 0.002 or less). On its own, agreement goes from 0.701 (1 sample) to 0.784 (5), so on top of the single answer's features most of its signal is already covered.
- **Extra samples help B more:** +0.044 (lr), +0.031 (rf) and +0.035 (gb) ROC-AUC from `plus_answer` to 5 samples, nearly all of it by 3 or 4 samples. B's PR-AUC moves less: +0.005 (rf), +0.014 (lr) and +0.024 (gb).
- **Database identity adds almost nothing:** +0.001 to +0.003 ROC-AUC for A, and −0.001 to +0.005 for B. B's PR-AUC rises 0.008 to 0.022, within its seed std (up to 0.021).
- **Classifier types:** for A, logistic regression is best or tied at every step from 1 sample on. With question and schema only, the random forest is best (0.679 against 0.636 for lr). For B, the random forest and gradient boosting beat logistic regression at every step, by 0.01 to 0.03 ROC-AUC and 0.02 to 0.04 PR-AUC.
- **Flagged shares, A:** with `plus_answer` (no extra calls), precision at 20% escalation is already 0.971 to 0.989 (0.982 to 0.989 at 5 samples).
- **Settings:** logistic regression picks C = 1 for A from `plus_answer` on, and C = 0.01 for B at every step. Gradient boosting picks depth 2 and 100 rounds everywhere except `before_generation` for A (depth 4).
- **Checks:** E3's `plus_agree_k5` rows equal E2's 5-fold rows exactly (same features and seeds), and a separate random-forest-only E3 run gave identical random-forest rows. `outputs/e3_results.csv` and `outputs/e3_scores.csv` hold the all-three run.
- Whether the +0.01 to +0.02 ROC-AUC that the samples add for A turns into routing accuracy worth about 0.91 s per sample is a question for the routing rehearsal and E5.

### Result: E2 and E3 rerun with wider settings grids (training)

On the first run, gradient boosting always picked the simplest settings in its grid, and logistic regression for B the strongest penalty, so both grids may have been cut off at that end. I widened them in `train.py` and reran E2 and E3 with the same commands and seeds:

- `gb`: depth 1, 2 or 4 and 50, 100 or 300 rounds (was depth 2 or 4 and 100 or 300 rounds).
- `lr`: C = 0.001, 0.01, 0.1, 1 or 10 (added 0.001).

The first-grid files are kept in `outputs/grid_v1/`. `outputs/e2_*.csv` and `outputs/e3_*.csv` now hold the wider-grid runs, which `route.py` will read.

- **Checks:** the random forest rows are identical to the first run (4 of 4 in E2, 16 of 16 in E3). So are logistic regression's rows for A, except `before_generation`, where it now picks C = 0.001.
- **Gradient boosting, A: unchanged choice.** It still picks depth 2 and 100 rounds. ROC-AUC 0.877 → 0.875 on 5-fold and 0.875 → 0.873 on LODO, and every E3 step is 0.001 to 0.004 lower, all within one seed std.
- **Gradient boosting, B: picks the simplest new settings, depth 1 and 50 rounds,** at every E3 step from `plus_answer` on and in both E2 splits. With depth 1 each tree makes one split, so the model is a sum of one-feature thresholds, with no interactions between features.

| Target B, `all_k5` | ROC-AUC, 5-fold | PR-AUC, 5-fold | ROC-AUC, LODO | PR-AUC, LODO |
| --- | --- | --- | --- | --- |
| `gb`, first grid (depth 2, 100 rounds) | 0.792 (0.006) | 0.382 (0.013) | 0.777 (0.000) | 0.356 (0.000) |
| `gb`, wider grid (depth 1, 50 rounds) | 0.800 (0.001) | 0.379 (0.005) | 0.797 (0.012) | 0.385 (0.013) |
| `lr`, first grid | 0.781 (0.003) | 0.347 (0.008) | 0.772 (0.001) | 0.343 (0.002) |
| `lr`, wider grid | 0.762 (0.010) | 0.338 (0.007) | 0.776 (0.011) | 0.345 (0.014) |
| `rf` (unchanged) | 0.795 (0.009) | 0.378 (0.018) | 0.784 (0.002) | 0.331 (0.001) |

- **E3, B, gradient boosting:** ROC-AUC is the same or higher at every step from `plus_answer` on (+0.001 to +0.010), and PR-AUC is a little lower (−0.003 to −0.013; −0.025 with database identity, 0.404 → 0.379).
- **E3, B, logistic regression:** C = 0.01 is still the most common pick, yet ROC-AUC is 0.015 to 0.019 lower for k = 2 to 5 (`plus_agree_k5` 0.781 → 0.762) and about the same for `plus_answer` and k = 1. Its seed std rose from 0.003 to 0.010 on 5-fold and from 0.001 to 0.011 on LODO, where its only randomness is which setting gets picked.
- **E3 sample gains for B, `plus_answer` to `plus_agree_k5`, now:** ROC-AUC +0.025 (lr), +0.031 (rf), +0.041 (gb); PR-AUC 0.000, +0.005, +0.023.

### Findings

- **For B, the simplest gradient boosting transfers best.** On unseen databases it is now the best type on both scores (ROC-AUC 0.797 and PR-AUC 0.385, against 0.784 and 0.331 for the random forest), and only 0.003 ROC-AUC below its 5-fold score (0.015 before). On 5-fold the change is a wash: ROC-AUC +0.008, PR-AUC −0.003.
- **B's signal looks like a sum of single clues.** The best gradient boosting uses no feature interactions, and logistic regression wants a strong penalty. With 161 positives, extra freedom mostly fits noise.
- **For A, the first grid wasn't holding gradient boosting back.**
- **Gradient boosting for B now sits at the edge of the wider grid** (depth 1 is the smallest possible; 50 rounds is the fewest offered). I stop widening here: fewer rounds would only shrink the same one-split-per-tree model further.
- **Offering logistic regression an extra setting made B worse on 5-fold,** although its usual pick didn't change. Not yet explained; a likely cause is that the out-of-fold scores of all folds are ranked together, and a fold whose model picked C = 0.001 has its scores squeezed close to 0.5, out of line with the other folds.

### Result: why logistic regression for B dropped (pooled vs. per-fold ROC-AUC)

`train.py` measures ROC-AUC after pooling the out-of-fold scores of all 5 folds, and each fold's scores come from a different model. I rebuilt the folds from the seeds (stratified 5-fold on `label_b`) and compared the pooled ROC-AUC with the mean of the 5 per-fold ROC-AUCs, for E2's B rows, first grid vs. wider grid. The rebuilt folds match `train.py`'s: the logistic regression folds whose setting didn't change have exactly the first run's score spread.

| B, 5-fold, mean over seeds | Pooled ROC-AUC | Mean per-fold ROC-AUC | Std of scores within a fold |
| --- | --- | --- | --- |
| `lr`, first grid | 0.781 | 0.784 | 0.180 to 0.226 |
| `lr`, wider grid | 0.762 | 0.778 | the same, except 6 of 15 folds at 0.100 to 0.113 |
| `gb`, first grid (depth 2, 100 rounds) | 0.792 | 0.796 | 0.226 to 0.274 |
| `gb`, wider grid (depth 1, 50 rounds) | 0.800 | 0.805 | 0.184 to 0.242 |

- **Logistic regression:** the 6 folds that picked C = 0.001 (2, 1 and 3 for seeds 0, 1 and 2) have about half the score spread of the others. Per seed, the pooled score sits 0.019, 0.010 and 0.017 below the per-fold mean, against 0.002 to 0.003 on the first grid.
- **Gradient boosting:** the gain on the wider grid is real within folds too (per-fold mean 0.796 → 0.805), not a side effect of pooling.

### Findings

- **Logistic regression's drop for B (0.781 → 0.762) is mostly a pooling effect.** About 0.013 of the 0.019 comes from ranking squeezed folds together with normal ones; about 0.006 is a real loss within the folds that picked C = 0.001.
- **Every pooled number in E2 and E3 understates the per-fold ranking a little:** by 0.001 to 0.008 when the folds pick the same settings, and up to 0.019 when they don't. The direction is the same for every classifier, and no conclusion or candidate changes.
- **The same effect would distort the routing rehearsal** if it ranked all 1,034 out-of-fold scores together. On the test set a single model scores all 500 questions, so ranking within each fold (each fold is a small test set with its own model) matches E4 better.

### Run: fold numbers saved with the out-of-fold scores

- `train.py` now writes a `fold` column into `--scores_out` (which held-out part scored each question: 0 to 4 for 5-fold, 0 to 10 for LODO). Reran E2 and E3 with the same commands.
- Checks: every score and every results row is identical to the run before the change; each 5-fold run has 5 folds of 206 to 207 questions, and each LODO run has 11.
- **Decision:** the routing rehearsal ranks questions within their fold and escalates the same share of every fold. Each fold is then a small test set scored by one model, as the 500 test questions will be in E4, and the fold-to-fold differences in score scale found above don't leak into the ranking.

### Result: routing rehearsal on the training questions (`scripts/route.py`)

`route.py` simulates routing on the 1,034 training questions from the saved right/wrong marks (7B and 32B temperature-0 answers, the 7B's 5 samples) and E3's out-of-fold scores. No model is called: escalating a question means using the 32B's saved mark instead of the 7B's. Classifier routers rank questions within their fold and escalate the same share of every fold; rule routers rank all questions together. Ties are broken by one fixed random order (seed 0). Classifier numbers are means over seeds 0 to 2. Paired bootstrap: 10,000 resamples (seed 0) of each question's outcome averaged over the seeds. McNemar's exact test is run per seed and the largest p is reported. Outputs: `outputs/rehearsal_routers.csv`, `outputs/rehearsal_tests.csv`, `outputs/rehearsal_curves.csv`.

- **Checks:** every earlier reference number is reproduced: always-small 54.26, always-large 64.41, majority answer 58.22 (fixes 62, breaks 21), crash rule 59.67 at 11.1%, at most 0 / 2 / 4 of 5 samples agree 59.86 at 13.3% / 62.96 at 25.1% / 64.70 at 47.9%, challenging 54.93 at 4.2%, challenging + moderate 56.96 at 24.9%, oracle 69.83 at 15.6%, oracle with the majority answer kept 70.60 (at 12.4%). Random at share r is 54.26 + 10.15 r.
- **New rule points:** at most 1 of 5 agree 61.32 at 18.1%; at most 3 of 5 agree 63.15 at 34.9%. The largest gain over random is "at most 2 of 5 agree" (+6.15), so that is the agreement rule for H3.

| Router | EX at 20% | EX at 30% | EX at 50% | Mean EX, 10-50% | Share matching always-large |
| --- | --- | --- | --- | --- | --- |
| Random | 56.29 | 57.30 | 59.33 | 57.30 | 100% |
| Difficulty label | 56.29 | 57.54 | 59.09 | 57.14 | 96.2% |
| Crash rule | 60.25 | 60.25 | 61.70 | 60.42 | 87.8% |
| Agreement rule | 61.51 | 62.96 | 64.70 | 62.66 | 42.2% |
| Oracle | 69.83 | 69.83 | 69.83 | 69.43 | 10.2% |
| A `lr`, question only | 57.22 | 58.19 | 61.19 | 58.50 | 94.4% |
| A `lr`, 0 samples | 62.06 | 63.51 | 64.60 | 62.75 | 45.0% |
| A `lr`, 1 sample | 62.25 | 63.25 | 64.93 | 62.93 | 40.8% |
| A `lr`, 3 samples | 62.25 | 63.22 | 65.47 | 63.07 | 39.1% |
| A `lr`, 5 samples | 62.28 | 63.51 | 65.31 | 63.18 | 37.8% |
| A `gb`, question only | 57.61 | 59.12 | 61.28 | 58.84 | 86.5% |
| A `gb`, 0 samples | 62.15 | 63.19 | 64.64 | 62.88 | 40.3% |
| A `gb`, 1 sample | 62.15 | 63.41 | 64.99 | 63.01 | 39.0% |
| A `gb`, 3 samples | 62.25 | 63.67 | 65.02 | 63.05 | 38.9% |
| A `gb`, 5 samples | 62.12 | 63.86 | 65.25 | 63.30 | 32.4% |
| B `gb`, question only | 57.70 | 59.25 | 60.77 | 58.99 | 96.0% |
| B `gb`, 0 samples | 61.77 | 62.86 | 64.96 | 62.73 | 40.6% |
| B `gb`, 1 sample | 61.32 | 63.02 | 65.02 | 62.74 | 42.2% |
| B `gb`, 3 samples | 61.90 | 63.57 | 65.25 | 63.01 | 37.5% |
| B `gb`, 5 samples | 61.83 | 63.64 | 64.93 | 63.05 | 36.1% |

Seed stds are 0.02 to 0.49 for EX and up to 5.1 points for the share matching always-large, since the curves are nearly flat where they cross 64.41.

- **Selection (mean EX over 10-50% escalated, difference from the best [95% range]).** A: best is `gb` with 5 samples (63.30). `lr` 0 samples −0.55 [−1.06, −0.06]; `lr` 1 sample −0.37 [−0.81, +0.06]; `lr` 3 −0.23 [−0.57, +0.12]; `lr` 5 −0.12 [−0.46, +0.22]; `gb` 0 −0.42 [−0.81, −0.03]; `gb` 1 −0.29 [−0.58, +0.00]; `gb` 3 −0.25 [−0.46, −0.04]. The rule (fewest samples, then `lr`, among those whose range includes 0) picks **A `lr` with 1 sample**. B: best is 5 samples (63.05); 0 samples −0.33 [−1.03, +0.37], 1 sample −0.31 [−0.85, +0.23], 3 samples −0.04 [−0.37, +0.30]; the rule picks **B `gb` with 0 samples**. `gb` with 1 sample has an upper bound that rounds to +0.00, so its "within noise" label depends on rounding; it doesn't change either pick.
- **Against random and the difficulty label (H2):** every classifier using the 7B's answer is ahead by +5.0 to +6.6 points at 20, 30 and 50%, every 95% range above 0. The difficulty label is no better than random (mean EX over 10-50%: 57.14 against 57.30).
- **Against the agreement rule (H3):** the classifiers using the 7B's answer (without the majority answer) are −0.19 to +0.90 points from it at 20, 30 and 50%, and −0.48 to +0.16 at the rule's own 25.1%. No 95% range excludes 0. With the majority answer kept, B `gb` at 30% is the only one (+0.97).
- **Question-only routers:** +0.9 to +2.0 over random, and 3.4 to 5.2 points below the agreement rule, every range below 0.
- **Majority answer kept vs. the temperature-0 answer, same ranking:** +0.03 to +0.71 at 20 and 30%, −0.03 to 0.00 at 50%; no range excludes 0 and McNemar p ≥ 0.38. At 50% the two give identical outcomes for B `gb`.
- **B vs. A at the same number of samples (H5):** at 20%, B is 0.29 to 0.93 points lower. At 1 sample its bootstrap ranges exclude 0 (−0.93 [−1.71, −0.16] against `lr`, −0.84 [−1.55, −0.13] against `gb`), while McNemar's worst seed gives p 0.36 and 0.57. At 30 and 50%, −0.64 to +0.35, all ranges include 0.
- **Matching always-large (H6):** the classifiers using the 7B's answer reach 64.41 at 32.4 to 45.0% escalated, the agreement rule at 42.2%. At 50%, every one of them is above always-large (64.60 to 65.47).

### Findings

- **On training, the classifier ties the 5-sample agreement rule, but with 0 or 1 extra calls instead of 5.** A `lr` with no samples is +0.55, +0.55 and −0.10 points from the rule at 20, 30 and 50%. H3 as stated (beating the rule) does not hold on training; matching it at a fraction of the cost does.
- **H2 and H6 hold on training; H5 does not.** Predicting "fixable" (B) gives no gain over predicting "wrong" (A) at low shares, and is slightly worse at 20%.
- **Extra samples add little routing accuracy:** from 0 to 5 samples, mean EX over 10-50% rises 0.43 (A `lr`), 0.42 (A `gb`) and 0.32 (B `gb`) points.
- **Running the 7B's SQL is what makes routing work, now in accuracy:** routers deciding from the question alone gain 0.9 to 2.0 points over random, routers that see the 7B's answer and result gain 5 to 6.6.
- **Keeping the majority answer adds almost nothing once routing is on.** The questions where it changes the outcome are mostly the low-agreement ones the router escalates anyway; by 50% escalated they are all sent to the 32B for B `gb`.
- **The two paired tests can disagree near the edge.** The bootstrap uses seed-averaged outcomes, while McNemar takes the worst of 3 seeds, which is more conservative.

### Decision: frozen choices for E4 (before the test set is scored)

Chosen from the training rehearsal only. The test feature table and the test samples' agreement marks are still unscored.

- **Router A (main):** logistic regression, C = 1, features `plus_agree_k1` (the 7B's answer, its result, its confidence and agreement from 1 sample; 30 features), class weights, features scaled, row counts on a log scale as in `train.py`.
- **Router B (comparison):** gradient boosting (`HistGradientBoostingClassifier`), depth 1, 50 rounds, learning rate 0.05, features `plus_answer` (26 features, no samples), class weights, random state 0.
- **Final fit:** each trained once on all 1,034 training questions with these settings, without re-tuning, then scores the 500 test questions once.
- **Cutoffs:** escalate the top 20, 30 and 50% of the test risk scores (100, 150 and 250 questions); no labels are used. Ties are broken by one fixed random order (seed 0).
- **Agreement rule to beat (H3):** escalate when at most 2 of 5 samples agree with the 7B's answer. Router A is compared with it at the rule's own test share, and at 20, 30 and 50%.
- **Majority answer:** router A's ranking with the majority answer kept for questions that aren't escalated; reported as a comparison only.
- **Extra curves, not used to decide any hypothesis:** logistic regression for A with 0, 3 and 5 samples (C = 1), for the cost trade-off in E5, and with question-only features (`before_generation`, C = 0.001, its usual nested-CV setting), as a router that decides before generation.
- **Paired tests:** bootstrap with 10,000 resamples of the 500 questions (seed 0), 95% range from the 2.5th and 97.5th percentiles; McNemar's exact test (two-sided binomial on the discordant questions).
- **Official scores:** routed prediction files for routers A and B at 20, 30 and 50%, and for router A and the agreement rule at the rule's own share, scored with `evaluation_ex.py` and `evaluation_f1.py` at 400 s on an idle machine. Their EX must equal what the per-question marks give.

### Run: E4 code checked on training (no test data used)

- `route.py` now has two modes: `rehearse` (above) and `final`, which fits the frozen classifiers once on all 1,034 training questions, scores the routed questions once, runs the same curves and tests, and writes routed prediction files for the official scorer.
- **Rehearsal rerun after the change:** the routers, tests and curves files are identical to the first rehearsal; the tests file gains `includes_zero`, the "within noise" flag computed from the unrounded 95% range. On the unrounded range A `gb` with 1 sample is still within noise of the best, and both picks are unchanged.
- **Dry run of the final mode on training** (fit and routed on the same 1,034 questions, so its classifier numbers are in-sample): every reference number matches the rehearsal, all 7 frozen and extra routers ran, and the 8 routed files were written. The agreement rule's file at its own share gives 62.96 from the per-question marks, its known value. In-sample, router A's mean EX over 10-50% is 63.22, against 62.93 out of fold.
- **Routed files checked independently:** recounting EX straight from the 8 dry-run files (each question's SQL is the 7B's or the 32B's, then that answer's right/wrong mark) gives the same 8 numbers `route.py` printed (62.38 to 65.57). In 7 to 12% of escalated questions the 32B wrote exactly the 7B's SQL (for example 190 of 207 entries differ at 20%). The dry-run files were then deleted.

## 2026-10-27: E4, routing the test set (main result)

### Run: `route.py --mode final` on the 500 Mini-Dev questions

`python scripts/route.py --mode final --features outputs/features_train.csv --test_features outputs/features_test.csv --runs outputs/minidev --agree_rule 2 --out outputs/e4`, with every choice as frozen above (committed before the run). The frozen classifiers were fit once on the 1,034 training questions and scored each test question once. Outputs: `outputs/e4_routers.csv`, `e4_tests.csv`, `e4_curves.csv`, `e4_scores.csv` and 8 routed prediction files. One model per router, so no seed std. The official scorer's check of the routed files is still to run.

- **Checks against E1:** always-small 49.80, always-large 57.80, majority answer 51.60 (fixes 33, breaks 24), challenging 52.20 at 20.4%, challenging + moderate 56.00 at 70.4%, oracle 63.80 at 14.0% (63.80 at 12.2% with the majority answer kept), random 51.40 / 52.20 / 53.80 at 20 / 30 / 50%. All match.
- **Rule routers at their own test shares:** crash rule 54.00 at 11.4%; at most 0 / 1 / 2 / 3 / 4 of 5 samples agree: 55.00 at 17.2%, 55.40 at 26.4%, 55.00 at 34.6%, 56.00 at 43.0%, 57.00 at 57.0%. The frozen rule (at most 2) escalates 34.6% on test against 25.1% on training, and gains +2.43 over random against +6.15.

| Router (test) | EX at 20% | EX at 30% | EX at 50% | Mean EX, 10-50% | Share matching always-large |
| --- | --- | --- | --- | --- | --- |
| Random | 51.40 | 52.20 | 53.80 | 52.20 | 100% |
| Difficulty label | 52.00 | 53.20 | 55.20 | 53.21 | 99.4% |
| Crash rule | 54.20 | 54.80 | 56.00 | 55.09 | 98.4% |
| Agreement rule (at most 2 of 5) | 55.20 | 55.20 | 56.60 | 55.15 | 76.8% |
| **A: `lr`, 1 sample (main)** | **56.00** | **57.20** | **57.40** | **56.41** | **40.8%** |
| B: `gb`, 0 samples | 57.00 | 57.60 | 58.20 | 56.90 | 30.2% |
| A, majority answer kept | 55.20 | 55.80 | 57.00 | 55.33 | 53.2% |
| A `lr`, 0 samples (extra) | 56.20 | 56.80 | 57.60 | 56.37 | 33.0% |
| A `lr`, 3 samples (extra) | 56.00 | 57.60 | 57.20 | 56.48 | 27.6% |
| A `lr`, 5 samples (extra) | 56.00 | 57.00 | 58.00 | 56.54 | 33.6% |
| A `lr`, question only (extra) | 50.80 | 52.00 | 54.00 | 51.89 | 99.8% |
| Oracle | 63.80 | 63.80 | 63.80 | 63.59 | 8.0% |

**Router A against the baselines** (EX difference in points [95% bootstrap range], McNemar p):

| Baseline | 20% | 30% | 50% | Rule's own share (34.6%, 173 escalated) |
| --- | --- | --- | --- | --- |
| Random | +4.6 [+2.72, +6.60] | +5.0 [+3.00, +7.06] | +3.6 [+1.70, +5.60] | |
| Difficulty label | +4.0 [+1.40, +6.60], p 0.0037 | +4.0 [+1.40, +6.60], p 0.0037 | +2.2 [+0.00, +4.60], p 0.090 (range includes 0) | |
| Agreement rule | +0.8 [−1.40, +3.00], p 0.58 | +2.0 [−0.20, +4.20], p 0.11 | +0.8 [−1.20, +2.80], p 0.56 | +2.6 [+0.60, +4.60], p 0.019 |

- **B vs. A (H5):** +1.0 [+0.00, +2.20] p 0.13 at 20% (the range includes 0), +0.4 [−1.40, +2.20] p 0.83 at 30%, +0.8 [−1.00, +2.60] p 0.50 at 50%.
- **Router B against the baselines:** ahead of random and the difficulty label at all three shares, every range above 0 (difficulty at 50%: +3.0 [+0.60, +5.60], p 0.028); against the agreement rule +1.8 / +2.4 / +1.6 at 20 / 30 / 50% (ranges include 0) and +2.6 [+0.40, +5.00], p 0.041 at the rule's share.
- **Majority answer kept vs. the 7B's answer, same ranking:** −0.8 [−3.20, +1.80], −1.4 [−3.40, +0.60], −0.4 [−1.20, +0.40]; McNemar p 0.64, 0.23, 0.63.
- **Question-only router vs. random:** −0.6, −0.2, +0.2, every range includes 0; against the agreement rule −4.4, −3.2, −2.6 (the first two ranges below 0).
- **Routed files** (EX from the per-question marks, for the official check): A 56.00 / 57.20 / 57.40 at 20 / 30 / 50%, B 57.00 / 57.60 / 58.20, A at the rule's share 57.60, the agreement rule at its share 55.00.

### Hypotheses on the test set (router A, the frozen main router)

- **H2 (beats random and the difficulty label at 20, 30 and 50%): partly holds.** Five of the six comparisons have 95% ranges above 0. At 50%, router A is +2.2 over the difficulty label with a range touching 0 (+0.00 to +4.60, p 0.090). Router B and the 0-sample A pass all six, but neither was the frozen main router.
- **H3 (beats the best agreement rule at the same share): holds at the rule's own share,** +2.6 points (57.60 vs. 55.00 with 173 questions escalated each), range +0.60 to +4.60, McNemar p 0.019. At the fixed 20, 30 and 50% shares the differences are positive (+0.8 to +2.0) but every range includes 0. On training the two tied.
- **H5 (B beats A at low shares): not supported.** B is ahead at every share (+0.4 to +1.0), the opposite direction from training, but no range excludes 0.
- **H6 (matches always-large while sending at most half): holds.** Router A first reaches 57.80 at 40.8% escalated (B at 30.2%). Router A's curve then dips: it is at 57.40 at 50%, while B is at 58.20.

### Findings

- **The agreement rule's fixed threshold doesn't carry over to the test set; the classifier's cutoffs do.** The test samples agree less (all 5 give the same result on 44.0% of test questions vs. 52.4% of training), so "at most 2 of 5 agree" escalates 34.6% instead of 25.1%, and its gain over random drops from +6.15 to +2.43 points. The classifiers escalate a fixed share of their own ranking, and the frozen routers A and B stay +3.6 to +5.6 points over random.
- **Running the 7B's SQL is what makes routing work, now on the test set:** the question-only router is no better than random (−0.6 to +0.2), while the same classifier with the 7B's answer gains +3.8 to +4.8.
- **Extra samples add nothing measurable on the test set:** mean EX over 10-50% is 56.37, 56.41, 56.48 and 56.54 with 0, 1, 3 and 5 samples (+0.17 points from 0 to 5, less than one question), and B with no samples is the highest of all (56.90).
- **Keeping the majority answer slightly hurts once routing is on** (−0.4 to −1.4, not significant), although alone it beats the 7B's answer (51.60 vs. 49.80).
- **On the test set the difficulty label is a little above random** (+0.6 to +1.4 points at 20, 30 and 50%), unlike training; its significance against random wasn't part of the frozen tests.
- **Routing gains are smaller in points on test than on training,** as expected from the smaller gap between the models (8.0 vs. 10.15 points): router A is +3.6 to +5.0 over random on test against +5.6 to +6.0 on training.
- Many comparisons were run; the hypothesis verdicts above use only the pre-registered comparisons for router A.

## 2026-11-02: E4, official scores of the routed files

### Result: official EX and Soft F1 of the 8 routed files (test, 400 s, idle machine)

Scored with `evaluation_ex.py` and `evaluation_f1.py` from Mini-Dev, as frozen. **All 8 official EX totals equal the per-question numbers from `route.py`**, so the 2026-10-27 hypothesis verdicts stand unchanged: H2 partly holds, H3 holds at the rule's own share, H5 not supported, H6 holds.

| Routed file (test) | Escalated | EX (simple / moderate / challenging) | EX total | Soft F1 (simple / moderate / challenging) | Soft F1 total |
| --- | --- | --- | --- | --- | --- |
| Always-small (7B, E1) | 0 | 66.22 / 47.20 / 32.35 | 49.80 | 68.01 / 50.64 / 35.45 | 52.68 |
| A at 20% | 100 | 71.62 / 54.00 / 38.24 | 56.00 | 74.39 / 58.15 / 42.28 | 59.72 |
| A at 30% | 150 | 72.30 / 55.20 / 40.20 | 57.20 | 75.14 / 59.77 / 44.09 | 61.12 |
| A at 50% | 250 | 70.95 / 55.60 / 42.16 | 57.40 | 73.79 / 60.89 / 47.39 | 61.95 |
| B at 20% | 100 | 71.62 / 54.40 / 42.16 | 57.00 | 74.39 / 58.55 / 46.30 | 60.74 |
| B at 30% | 150 | 72.30 / 54.80 / 43.14 | 57.60 | 75.07 / 59.18 / 46.92 | 61.38 |
| B at 50% | 250 | 72.30 / 56.00 / 43.14 | 58.20 | 74.60 / 60.19 / 48.51 | 62.07 |
| A at the rule's share | 173 | 72.30 / 55.60 / 41.18 | 57.60 | 75.14 / 60.44 / 45.61 | 61.76 |
| Agreement rule (at most 2 of 5) | 173 | 69.59 / 54.00 / 36.27 | 55.00 | 72.37 / 58.04 / 42.37 | 59.09 |
| Always-large (32B, E1) | 500 | 72.30 / 54.80 / 44.12 | 57.80 | 74.97 / 59.32 / 47.89 | 61.62 |

### Findings

- **Soft F1 tells the same story as EX.** It is 3.7 to 4.6 points above EX for every routed file. Router A beats the agreement rule at the rule's share by +2.67 Soft F1 (EX +2.6). B is ahead of A by +1.02 / +0.26 / +0.12 Soft F1 at 20 / 30 / 50% (EX +1.0 / +0.4 / +0.8). There is no paired test on Soft F1, because only EX has per-question marks.
- **By Soft F1, routing passes always-large sooner than by EX.** A at the rule's share (61.76, 34.6% escalated), A at 50% (61.95) and B at 50% (62.07) are all above always-large's 61.62. By EX, only B at 50% is above always-large among these files (58.20 vs. 57.80).
- **B's lead over A at 20% is mostly on challenging questions:** 285 vs. 280 correct, made up of +4 challenging and +1 moderate, with simple tied (106 each).
- **Escalating more can break simple questions the 7B had right.** From 30% to 50%, router A sends 100 more questions to the 32B for a net +1 question: simple −2 (107 to 105), moderate +1, challenging +2. B at 50% matches always-large on simple (107), is above it on moderate (140 vs. 137) and gets one fewer challenging question (44 vs. 45).

## 2026-11-02: E5, time and cost per router

### Decision: E5 choices (before any E5 number is computed)

- **Questions and routers:** the 500 test questions and every E4 router, with E4's escalated questions. `scripts/cost.py` rebuilds the queues from `e4_scores.csv` with `route.py`'s ranking and tie-break, and stops unless its EX equals `e4_routers.csv` at 20, 30 and 50% for all 12 routers.
- **Seconds per question:** the model calls plus running their SQL, one question at a time on this laptop (Apple M5 Max, 64 GB, Ollama 0.35.1, the 4-bit models). Building the features and running the classifier take milliseconds and are left out.
- **Routers that decide after the 7B answers:** the 7B's answer, its k tries and running their SQL for every question, plus the 32B call and running its SQL for the escalated ones. k is 1 for router A, 0 for B, the crash rule and the oracle, 0, 3 or 5 for the extra A curves, and 5 for the agreement rule and for A with the majority answer kept.
- **Routers that decide before the 7B answers** (random, the difficulty label, the question-only router): escalated questions go straight to the 32B and skip the 7B. Always-large is the 32B call alone.
- **Tries in a row vs. together:** in a row means the answer, then each try after the last one; together means the answer and the k tries sent at once, timed until the last reply. Together is measured for k = 1, 3 and 5 (no router uses 2 or 4).
- **Timing run** (`scripts/timing.py`, one sitting, idle machine, questions in file order, an untimed warm-up call before each pass): first the together passes for k = 1, 3 and 5 on a server started with `OLLAMA_NUM_PARALLEL=6`; then, on the normal server, the 7B's answer and 5 tries in a row, and the 32B's answer. Both servers use the Homebrew service's settings (`OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`), so the only difference is answering requests in parallel. The parallel server only holds the 7B: in a 3-question smoke test, the 32B took 45 GB there with 6 slots (default KV cache) and pushed the 7B out. The requests are the saved runs' requests: temperature 0 with log-probabilities for the 7B's answer, 0.7 with seeds 0 to 4 for the tries, temperature 0 for the 32B. The timed replies are only used for their seconds; the routers keep the saved answers. The saved runs' seconds are reported as well, to show how much timing moves between sittings (the 7B's answer took 0.99 s per question in E1 and 0.86 s in the 10 Oct log-probability run).
- **Running the SQL:** the seconds saved by `check.py` (about 0.04 s per query).
- **Tokens:** from the saved runs, which hold the replies the routers used.
- **Dollars:** only 32B calls are paid, at OpenRouter's listed price for `qwen/qwen-2.5-coder-32b-instruct` (served by Cloudflare): $0.66 per million input tokens and $1.00 per million output tokens, checked 2 Nov 2026. Together AI lists $0.80 / $0.80, but only on dedicated servers. Each router's spend is also given as a share of always-large's, which barely depends on the price.
- **Points reported:** always-small, always-large, each router at 20, 30 and 50%, the crash and agreement rules and router A at the rules' own shares, and each router's first point matching always-large's EX. E5 decides no hypothesis.

### Result: E5 from the saved runs' seconds (`cost.py` without `--timing`)

`python scripts/cost.py --price_in 0.66 --price_out 1.00 --out outputs/e5_saved`. EX equals E4's for all 12 routers at 20, 30 and 50%, so the escalated questions are E4's. No together times here; those come from the timing run.

- **Per test question, saved runs:** the 7B's answer 0.986 s, one try 0.909 s (5 in a row 4.546 s), the 32B's answer 4.146 s; running the SQL 0.037 s (7B answer), 0.185 s (5 tries) and 0.047 s (32B answer). Tokens: prompt 1,014 on average, replies 56 (7B) and 59 (32B). At the frozen price the 32B costs $0.728 per 1,000 questions.

| Router | Escalated | EX | Seconds per question (tries in a row) | $ per 1,000 questions | $ vs. always-large |
| --- | --- | --- | --- | --- | --- |
| Always-small | 0% | 49.80 | 1.022 | 0 | 0% |
| B (0 tries) | 20 / 30 / 50% | 57.00 / 57.60 / 58.20 | 1.979 / 2.482 / 3.272 | 0.139 / 0.208 / 0.352 | 19.1 / 28.6 / 48.4% |
| B, first match of always-large | 30.2% | 57.80 | 2.488 | 0.210 | 28.8% |
| A (1 try) | 20 / 30 / 50% | 56.00 / 57.20 / 57.40 | 3.050 / 3.604 / 4.480 | 0.138 / 0.216 / 0.362 | 19.0 / 29.7 / 49.7% |
| A, first match of always-large | 40.8% | 57.80 | 4.077 | 0.297 | 40.8% |
| A with 0 tries, first match | 33.0% | 57.80 | 2.728 | 0.235 | 32.2% |
| Agreement rule (5 tries) | 20 / 30 / 50% | 55.20 / 55.20 / 56.60 | 6.775 / 7.274 / 8.141 | 0.145 / 0.220 / 0.361 | 19.9 / 30.3 / 49.6% |
| Agreement rule at its share | 34.6% | 55.00 | 7.475 | 0.252 | 34.6% |
| Question-only router | 20 / 30 / 50% | 50.80 / 52.00 / 54.00 | 1.772 / 2.128 / 2.817 | 0.138 / 0.212 / 0.364 | 18.9 / 29.2 / 50.0% |
| Always-large | 100% | 57.80 | 4.193 | 0.728 | 100% |

- **Dollars follow the share escalated almost exactly** (within 1.6 points at every reported point; B's escalated questions are slightly shorter): escalated questions have about average prompt and reply lengths, so the price only scales the dollar column.
- **With no tries, routing saves time as well as money:** B matches always-large's EX at 59% of its time (2.49 vs. 4.19 s) and 29% of its dollars.
- **One try in a row eats most of the time saving:** router A first matches always-large at 4.08 s, only 3% faster than always-large, though at 41% of its dollars.
- **Five tries in a row make a router slower than always-large at every share** (the agreement rule: 6.8 to 9.1 s). Whether sending the tries together fixes this is what the timing run measures.

## 2026-11-06: E5, the timing run

### Run: `scripts/timing.py`, all 5 passes on the 500 test questions

- **Together passes** (answer + 1, 3 and 5 tries sent at once, 7B only, server with `OLLAMA_NUM_PARALLEL=6`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`): 15:25, 28:57 and 32:15 min. The parallel check before each pass (the same 128-token request) took 1.54 / 2.11 / 2.52 s alone and 3.07 / 6.10 / 6.84 s six at once, so the server answered in parallel every time.
- **Sequential and 32B passes** on the Homebrew service (same flash-attention and KV-cache settings, no parallel setting). Changed from the frozen plan: the run was not one sitting. The together passes ran on 2 Nov and the last two passes finished on 5 Nov. The sequential pass was stopped after 6 questions and resumed, with a new untimed warm-up first.
- **Temperature 0 is not fully repeatable here.** The timed answer SQL equals the saved run's for 479 / 480 / 473 / 481 of 500 questions (sequential, together 1 / 3 / 5) and 493 of 500 for the 32B. The timed replies are only used for their seconds; EX, tokens and dollars come from the saved runs.
- **Slowdown check:** each together pass's time divided by the in-a-row time for the same questions shows no rise from the first 100 questions to the last 100 (k = 1: 0.78 / 1.16 / 0.99 / 0.92 / 0.96; k = 5: 0.87 / 0.72 / 0.65 / 0.65 / 0.64). So the slower single requests in the parallel checks don't show up in the question timings.

### Result: E5 with the timing run's seconds (`cost.py --timing`)

`python scripts/cost.py --timing outputs/timing_minidev.jsonl --price_in 0.66 --price_out 1.00 --out outputs/e5`. EX equals E4's for all 12 routers at 20, 30 and 50%.

- **Per call:**

  | Call | Timing run | Saved runs | Change |
  | --- | --- | --- | --- |
  | 7B answer | 1.064 s | 0.986 s | +8% |
  | 7B try | 0.902 s | 0.909 s | −1% |
  | 32B answer | 4.040 s | 4.146 s | −3% |

  The 7B's answer moves the most between sittings: 0.86 s in the 10 Oct log-probability run, 0.99 s in E1 and 1.06 s here.
- **Answer + tries, in a row vs. together:**

  | Tries | In a row | Together | Saved |
  | --- | --- | --- | --- |
  | 1 | 1.901 s | 1.851 s | 0.049 s (2.6%) |
  | 3 | 3.755 s | 3.475 s | 0.281 s (7.5%) |
  | 5 | 5.572 s | 3.871 s | 1.702 s (30.5%) |

| Router | Escalated | EX | Seconds per question (in a row / together) | Seconds vs. always-large (in a row / together) | $ per 1,000 questions | $ vs. always-large |
| --- | --- | --- | --- | --- | --- | --- |
| Always-small | 0% | 49.80 | 1.101 | 27% | 0 | 0% |
| Oracle, first match of always-large | 8.0% | 57.80 | 1.442 | 35% | 0.055 | 7.5% |
| Crash rule at its share | 11.4% | 54.00 | 1.641 | 40% | 0.079 | 10.8% |
| B (0 tries) | 20 / 30 / 50% | 57.00 / 57.60 / 58.20 | 2.028 / 2.518 / 3.285 | 50 / 62 / 80% | 0.139 / 0.208 / 0.352 | 19.1 / 28.6 / 48.4% |
| B, first match | 30.2% | 57.80 | 2.524 | 62% | 0.210 | 28.8% |
| A with 0 tries, first match | 33.0% | 57.80 | 2.763 | 68% | 0.235 | 32.2% |
| A (1 try) | 20 / 30 / 50% | 56.00 / 57.20 / 57.40 | 2.978 / 3.506 / 4.337 and 2.929 / 3.457 / 4.287 | 73 / 86 / 106% and 72 / 85 / 105% | 0.138 / 0.216 / 0.362 | 19.0 / 29.7 / 49.7% |
| A at the agreement rule's share | 34.6% | 57.60 | 3.695 / 3.646 | 90 / 89% | 0.248 | 34.1% |
| A, first match | 40.8% | 57.80 | 3.961 / 3.912 | 97 / 96% | 0.297 | 40.8% |
| A with 3 tries, first match | 27.6% | 57.80 | 5.322 / 5.041 | 130 / 123% | 0.197 | 27.1% |
| A with 5 tries, first match | 33.6% | 57.80 | 7.468 / 5.767 | 183 / 141% | 0.247 | 33.9% |
| Agreement rule (5 tries) | 20 / 30 / 50% | 55.20 / 55.20 / 56.60 | 6.786 / 7.282 / 8.121 and 5.085 / 5.580 / 6.420 | 166 / 178 / 199% and 124 / 137 / 157% | 0.145 / 0.220 / 0.361 | 19.9 / 30.3 / 49.6% |
| Agreement rule at its share | 34.6% | 55.00 | 7.473 / 5.772 | 183 / 141% | 0.252 | 34.6% |
| Question-only router | 20 / 30 / 50% | 50.80 / 52.00 / 54.00 | 1.815 / 2.149 / 2.779 | 44 / 53 / 68% | 0.138 / 0.212 / 0.364 | 18.9 / 29.2 / 50.0% |
| Always-large | 100% | 57.80 | 4.086 | 100% | 0.728 | 100% |

The together column is the same as in a row for routers with no tries.

### Findings

- **The timing run confirms the saved-run numbers.** Every reported point is within 0.15 s of the 2 Nov table (the largest gap is A at 50%, 4.337 vs. 4.480 s): B's first match 2.524 vs. 2.488 s, A's 3.961 vs. 4.077 s, the agreement rule at its share 7.473 vs. 7.475 s, always-large 4.086 vs. 4.193 s. The dollar columns are unchanged.
- **Only routers without tries save time.** B matches always-large's EX at 62% of its time and 29% of its dollars, and A with 0 tries at 68% and 32%. Router A with 1 try costs 41% of the dollars but almost the same time (97% in a row, 96% together).
- **Sending the tries together only pays off at 5 tries, and not enough.** Even together, the answer plus 5 tries take 3.871 s, 96% of one 32B answer (4.040 s). So every 5-try router is slower than always-large at every share. The agreement rule at its share takes 141% of always-large's time for 35% of its dollars and 2.8 points less EX.
- **The likely reason is that the in-a-row requests reuse the processed prompt.** I fit seconds = a + b · reply tokens + c · prompt tokens per call type:

  | Call type | Seconds per 1,000 prompt tokens |
  | --- | --- |
  | 7B in a row | 0.07 to 0.13 |
  | 32B (one at a time) | 0.07 |
  | 7B, answer + 1 try together | 0.77 to 0.79 |
  | 7B, answer + 5 tries together | 0.24 |

  On the normal server the prompt is mostly already processed: the tries share the answer's prompt, and consecutive questions on the same database share the schema. Sent together, the requests go to different server slots and mostly process the prompt again. On prompts of 1,500+ tokens (51 questions), the answer plus 1 try together take 1.46 times as long as in a row. With 5 tries, decoding the replies in one batch outweighs this. A server that reads the prompt once and decodes all k + 1 replies together might do better; I haven't tested one.
- **Time saving is smaller than dollar saving because the escalated questions are slow on the 32B.**

  | Questions | 32B seconds | Reply tokens | Prompt tokens |
  | --- | --- | --- | --- |
  | B's first 151 escalated | 4.66 | 69.3 | 947 |
  | All 500 | 4.04 | 59.1 | 1,014 |

  For the 32B, each reply token takes about 60 ms, while the prompt is mostly reused. So time follows reply length, and dollars mostly follow prompt length. The replies of A's first 204 escalated questions (72.4 tokens) and A-with-0-tries' first 165 (75.2) are also 17 to 27% longer than average. This corrects the 2 Nov finding that escalated questions have about average reply lengths.
