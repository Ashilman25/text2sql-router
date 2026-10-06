# Project journal

A running log of what was done, what came out of it, and what changed. Newest entry at the bottom. Each entry: what was done, results with numbers, findings, and what changed because of them.

---

## 2026-10-05: Repo, environment and data setup

### Starting point

- The repo has `scripts/generate.py`, `scripts/gold_check.py`, `requirements.txt` and `.gitignore`, copied from the setup guide. Only the README is pushed to GitHub (`Ashilman25/text2sql-router`).
- The project overview and setup guide in `docs/` are the plan, not final. The proposal (10 to 12 pages, LaTeX) is the next deliverable.
- My laptop is an Apple M5 Max with 64 GB (Ollama sees 51.8 GB of GPU memory), so it can run the 32B model. Large-model runs happen here.

### Environment

- `mini_dev/` is cloned at commit `abd11b6` (2026-09-05).
- `.venv` uses Python 3.11.15, and all of `requirements.txt` installs and imports.
- Ollama 0.35.1 is installed with Homebrew. `brew services start ollama` registered, but the server never stayed up when started from a Claude Code session, so I ran `ollama serve` directly. Still to check: whether the brew service works from a normal terminal.
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

The setup guide assumed both downloads ship identical SQLite files. Six of the 11 are byte-identical; five have the same schema but different rows:

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
- Ollama 0.35.1 picks its default context window from GPU memory (262,144 on this machine), not the 4,096 the setup guide mentions. `generate.py` sets 16,384 explicitly, so runs stay consistent across laptops.

### Docs changed

- `CLAUDE.md`: data layout and sources, `rebuild_gold.py`, separate database folders, `--db_root data/dev/dev_databases` for the dev run, the 400 s timeout, splitting on `question_id`.
- The setup guide in `docs/` is not updated yet. It still says the databases are shared, uses 30 s, and matches on question text.

- Added `docs/Project Explained.md`: a plain-language walkthrough of the whole project (what we train, how routing works, roadmap and status).

### Noted for later (not done)

- The `generate.py` cache is keyed only by question position, not by model, temperature or sample count, so reusing an `--out` silently skips questions.
- At temperature 0.7, the first of the 5 samples (the one saved as the prediction) is a random sample, not the default temperature-0 answer. I'm thinking of adding a temperature-0 answer to route, and using the 5 samples only for agreement features.
- The 32B model only needs to run on the 500 Mini-Dev questions, because the classifier learns from the small model's mistakes.
- Run the 5-sample generation per split, each with its own databases, so Mini-Dev features come from the Mini-Dev databases.

### Next

- Full Mini-Dev zero-shot runs with 1.5B, 7B and 32B, scored at 400 s, split by difficulty. These are the proposal's first numbers.
- Pick the small model (closest to 50% EX) and decide on the large model.
- Still open: proposal and final due dates, team size and roles.
- Commit and push `scripts/rebuild_gold.py`, `.gitignore` and `requirements.txt`. `CLAUDE.md` stays local (it's in `.gitignore`).

### Baseline runs started (1.5B first)

- I'm running the six commands (generate, then score, for each model) by hand in my own terminal, with `ollama serve` in a separate tab.
- **Finding: the 1.5B model can loop forever.** On question_id 1481 (index 6, challenging) it wrote an explanation, then `T65.Segment AS Segment64, T66.Segment AS Segment65, ...` without stopping. `generate.py` had no reply length limit, and Ollama 0.35.1 runs with context shift on, so when the reply filled the 16k window it kept going. The first two attempts sat on this question until I stopped them.
- **Change:** `generate.py` now caps replies with `--max_tokens` (default 1024, sent to Ollama as `num_predict`). Each sample also saves `done_reason`: `"stop"` means it finished normally, `"length"` means it hit the cap. With the cap, question 1481 ends after 5.17 s. The 6 answers saved before the change finished well under the cap, so they're unaffected (their `done_reason` is empty).
- After 115 of 500 questions: about 2.6 s per question, and 3 replies hit the cap.
- The 1.5B writes 290 to 410 tokens per reply (explanations around the SQL) compared with about 50 for 7B, even though the prompt asks for SQL only. `clean_sql` still extracts the SQL.
- Idea: replies that hit the cap are almost always wrong, so a "hit the cap" flag could be a useful classifier feature.
- Added a "Running the baselines" section to `docs/Project Explained.md`: the commands, how to read the progress bar, the Ollama log and the scorer output, and how the numbers feed the project.

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
- **Change:** the training data generation (5 samples per dev question) uses only the 7B, which matches the `dev_qwen7b_s5` command in `CLAUDE.md`. The 1.5B stays as a row in the E1 table, and I won't run it again.
- The "always small" end of the routing curve is 49.80.
- Accuracy still falls with difficulty (66 to 47 to 32), so the difficulty-label router stays a real baseline. But the 7B gets a third of the challenging questions right and misses a third of the simple ones, so difficulty alone won't separate right answers from wrong ones well. That leaves room for our classifier to win.
- New time estimate for the training data: 1,534 questions times 5 samples is about 7,700 calls. At about 1 s per call that's roughly 2 to 3 hours, not overnight. Replies at temperature 0.7 may be a little longer.

### Next

- Generate and score the 32B. That gives the top of the routing curve and the gap a router can recover.
- Then decide on the large model. If the 32B scores only a little above 49.80, consider an API model instead.

### Docs changed

- `docs/Project Explained.md`: added a table of contents at the top and a glossary at the end. The glossary explains every term used in the docs and code (about 100 terms), grouped as task and data, models, scoring, classifier, routing, project plan, and tools and files.
- `docs/Project Explained.md`: added three sections. "The models we have" covers the three Qwen2.5-Coder models: parameters (1.5B, 7.6B, 32.8B), 4-bit `Q4_K_M` compression, Apache 2.0 license, IDs, roles and scores. "How we got everything" covers how Ollama pulls and runs models, Hugging Face, the BIRD downloads and the full setup commands. "What each script does" covers the three scripts and the two borrowed Mini-Dev files. Also added the related terms to the glossary.
- Checked with `ollama show`: all three models are `Q4_K_M` quantized with a 32,768-token maximum context. Our scores are for these compressed versions, and the report should say so.
- `docs/Project Explained.md`: added "Why the 7B is the small model, not the 1.5B", a plain-language explanation of the choice: "small model" is a role, not a size. On the 1.5B, 82 of every 100 questions would be escalated anyway, and a classifier could reach 82% by always saying "wrong". On the 7B, a 50/50 split leaves half the answers worth keeping and forces the classifier to learn real warning signs.

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
- Catch: the 32B fixes only about 28% of the 7B's wrong answers, so "the 7B is probably wrong" doesn't mean "the 32B will fix it". That's fine for the plan: escalating a question both get wrong costs a call but never lowers accuracy. It's still worth a sentence in the proposal.

### Next

- Decide on the large model (leaning 32B).
- Write the proposal with these E1 numbers and the oracle, difficulty and random reference points.
- Add the per-question checker to `scripts/`. The classifier's training labels need it, and it can cache gold results instead of re-running question 701 every time.
- Training data: the 7B, 5 samples per question, on the dev questions against the dev databases, and on the Mini-Dev questions against the Mini-Dev databases (about 2 to 3 hours in total).

### Docs changed

- `docs/Project Explained.md`: added the 32B's score and speed, marked stage 1 done, and added a table of real reference points (always small, random, difficulty, always large, oracle). Also added the 7B vs 32B question-by-question table with a plain explanation, and updated "What's next". The oracle is now defined as "escalate what the small model gets wrong and the large model gets right".
- `docs/Project Explained.md`: rewrote "What's next" as a full checklist from now to the final report: decisions, proposal, training data, features, classifiers, routing, cost, extra scoring, report and stretch goals. Also updated the roadmap (stage 1 done; stages 2 and 3 next), added the looping fix to "What we've done", and added ROC-AUC, PR-AUC and F1 to the glossary.
- Plan changes written into it:
  - Run stage 3 on a training file of the 1,034 non-Mini-Dev questions instead of all 1,534.
  - Add a temperature-0 7B run for the training questions, so labels and SQL features come from the answer the router would keep.
  - Run 5 samples on Mini-Dev against its own databases. The new estimate is about 8,700 calls, roughly 2.5 to 3 hours.
  - Added an optional decision: also predict "worth escalating" (7B wrong and 32B right), which would need a 32B run on the training questions (about 70 minutes).

### Decision: the 32B is the large model

- The only other option was a paid API model, and nothing points to paying for one. The 32B is free and local, scores 57.80 (8.0 points above the 7B), and leaves 14 points between "always small" and the oracle (49.8 to 63.8). Its answers for all 500 test questions are already saved, so routing needs no more large-model runs. The Mini-Dev README's published API baselines with this kind of prompt are lower anyway (gpt-4 47.80).
- **Change:** `docs/Project Explained.md` now lists the 32B as the large model everywhere, and an API model only as a stretch comparison.

### Decision: train two classifier versions (A and B)

- **A, the main result:** "Is the 7B's answer wrong?" 50% "yes" on the test set (251 of 500), and the labels need only 7B runs.
- **B, the comparison:** "Is this question worth sending to the 32B?" (the 7B is wrong and the 32B is right). 14% "yes" on the test set (70 of 500).
- Why compare: a perfect A at 14% escalation reaches only 53.7% (just 28% of the 7B's wrong answers are fixable), while a perfect B reaches 63.8%. At 50% escalation both reach 63.8%. So B has the better curve in theory, but it learns from far fewer and subtler examples. Which one wins in practice is an empirical question.
- **Changes:**
  - Stage 3 adds a 32B run on the 1,034 training questions (temperature 0, dev databases, about 70 minutes), used only for B's labels, never as a feature.
  - Stages 5 and 6 train, ablate and draw routing curves for both versions, plus a direct A vs B comparison at equal escalation.
  - `docs/Project Explained.md` has a new "Two versions of the classifier" section, and the roadmap, "What's next" and glossary are updated to match.
