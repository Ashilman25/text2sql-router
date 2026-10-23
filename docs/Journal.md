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
