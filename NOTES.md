# Text2SQL SaaS — Project Notes

A running log of the project from the first fine-tuning check to now. Written so a cold start (you, weeks from now, or anyone else picking this up) can get oriented without re-deriving anything.

---

## 1. Project Overview

**Goal:** A Text2SQL SaaS product — takes a natural language question + a database schema, returns correct SQL.

**Base model:** Llama 3.2 3B Instruct, fine-tuned on the Spider text-to-SQL benchmark dataset.

**Eval methodology:** Execution accuracy — run the generated SQL and the gold SQL against the real database, compare the *results*, not the SQL text. This catches cases where SQL looks different but means the same thing, and catches cases where SQL looks similar but is subtly wrong.

**Environment split:**
- **Colab** — used for anything needing a GPU: loading the model, training, running eval loops.
- **VS Code (local)** — used for the actual product code: schema validation, database execution, inference strategies. No GPU needed for this part.

---

## 2. Phase 1 — First Fine-Tune Check

Started by manually testing one example: "average, min, max age of French singers."

**First bug found:** Generated SQL joined `singer` to `singer_in_concert` unnecessarily. This duplicated rows (one per concert a singer played in), which skewed the `avg()` — `min()`/`max()` still matched because duplicates don't affect extremes, only `avg()` was thrown off. This was the first sign of a recurring pattern: **spurious/unnecessary joins**.

---

## 3. Phase 2 — Building the Eval Loop

Built a full loop: load Spider dev set (1034 examples) → generate SQL for each → compare execution results → compute accuracy.

### Errors hit and fixed, in order:

1. **`AttributeError` on `.shape`** — `tokenizer.apply_chat_template()` returned a dict-like `BatchEncoding`, not a raw tensor, even with `return_tensors="pt"`. **Fix:** explicitly pass `return_dict=True`, then use `model.generate(**inputs, ...)` and index `inputs["input_ids"].shape[-1]` instead of `inputs.shape[-1]`.

2. **1034/1034 errors, 0% accuracy** — turned out the `generate_sql` function itself was the untested placeholder; the real issue was upstream of any SQL logic (the shape bug above). Lesson: a 100% failure rate almost always means a pipeline bug, not "the model is bad."

3. **No schema in the prompt** — after fixing the crash, accuracy was still very low (6.67%) because the eval prompt didn't include the database schema at all. The model was hallucinating column/table names it had no way to know. **Fix:** built `schema_lookup` (loaded from a HF dataset with `db_id`, `Schema (values (type))`, `Primary Keys`, `Foreign Keys` per database) and injected the real schema into every prompt.

4. **`'NoneType' object is not iterable`, 937/1034 errors** — after adding schema, most examples still failed. Root cause: `execute_queries()` catches SQL errors internally and returns `None` instead of raising; `compare_execution()` didn't check for `None` before calling `set()` on the result. This crash was misleadingly labeled as a runtime error, but it was really just "the query was invalid SQL" wearing a different hat.

**Result after all these fixes: 61.51% (636/1034) execution accuracy.** This became the real baseline.

---

## 4. Phase 3 — Failure Analysis

Categorized the ~400 failing examples into two buckets:
- **142 invalid SQL** (crashes on execution) — mostly hallucinated column/table names.
- **256 valid SQL, wrong result** — the SQL runs fine but the logic is wrong.

Manually reviewed 44 of the wrong-logic failures and found **5 recurring patterns:**

1. **Missing necessary join** — aggregating on the wrong table because a needed join was skipped (e.g. counting flights per airport without joining the flights table).
2. **Negation / NOT IN logic errors** — "has a dog but not a cat" type questions where the model used the wrong exclusion logic (`!=` on one row instead of a proper subquery).
3. **Schema confusion between near-duplicate tables** — mixing up `model_list`/`car_names`/`cars_data` and their join keys.
4. **Spurious unnecessary joins** — joining a table not needed for the question (the original bug from Phase 1, seen at scale).
5. **Semantic/comparison-target errors** — `MIN` vs `MAX` confusion, comparing to the wrong derived value.

---

## 5. Phase 4 — Inference-Time Fix: Execution-Guided Retry

Instead of always taking the model's greedy (single best-guess) output, added retry logic: try greedy first; if it fails to execute, sample several more candidates and return the first one that executes successfully.

**Result: 71.33% → actually first measured as 70.67% (106/150) on a 150-example sample** (full 1034 re-run wasn't completed due to Colab compute limits). This was a real, validated ~9 point improvement over the 61.51% baseline, from a purely inference-time change — no retraining needed.

**Debugging note:** Hit several stale-function/wrong-variable bugs during this phase — e.g. calling an old, broken retry function (`generate_sql_query_with_retry`) that was missing a `question` parameter, which silently shifted every other argument by one position and caused a `TypeError: string indices must be integers`. Lesson: when a function behaves nonsensically, check `inspect.getsource()` on it to see what's *actually* defined, rather than assuming the version you last wrote is the one running.

---

## 6. Phase 5 — Fine-Tuning Round 2: Contrastive Data

**Approach:** Took the 5 failure patterns from Phase 3, focused on the top 2 (missing joins, negation errors), and hand-wrote 26 contrastive example pairs — near-identical questions where only the join-necessity or negation logic differs, forcing the model to key off the actual semantics rather than surface pattern-matching.

**Training setup:**
- Continued training on top of the existing checkpoint (`checkpoint-122`), not a fresh LoRA from scratch — this matters, since starting fresh would have meant redoing the whole original fine-tune with a much smaller, narrower dataset.
- 26 examples oversampled 4x (104 total) + 971 original training examples = 1075 total.
- 2 epochs, learning rate 5e-5 (lower than the original 2e-4, since this was meant as a small nudge, not a full retrain).
- Kept the same `"text"` (fully-rendered chat template) format as the original training data, rather than switching to `prompt`/`completion` loss-masking — consistency with the existing training regime mattered more than the theoretical efficiency gain, for a small continuation pass.

**Result: checkpoint-270.**
- 71.33% (107/150) on the same 150-sample eval — essentially a wash vs. checkpoint-122's 70.67%.
- But: **7 of the 44 originally-failing examples were fixed**, including real conceptual improvement on the join-necessity pattern (e.g. the "airport with least flights" example went from grouping on the wrong table entirely to at least joining to the right table, even if not a perfect match).
- Some regressions also observed on unrelated examples during spot-checking (not fully quantified).

**Decision: kept checkpoint-270** — real logic-level improvement on the targeted patterns, no clear evidence of broad harm, even though the aggregate number didn't move much. Lesson: a small, narrow contrastive dataset can teach a real pattern without moving the aggregate number, because it's a small fraction of the overall failure surface.

## Fine-tuning Phase — Closed Out

Final checkpoint comparison:

| Approach | Accuracy | Sample size |
|---|---|---|
| checkpoint-122 (baseline, retry only) | 70.67% (106/150) | 150 |
| checkpoint-270 (+ contrastive data, retry only) | 71.33% (107/150) | 150 |
| checkpoint-270 + schema validation + majority voting | 72.00% (36/50) | 50 |

**Decision, final:** Using checkpoint-270 going forward.
- Schema validation: always on — cheap, catches real hallucinations
  (confirmed repeatedly in eval logs), no meaningful downside.
- Majority voting: optional — small accuracy gain (71.33% -> 72.00%,
  though on a smaller sample so not a high-confidence result), but
  costs more compute per query (multiple generations vs one). Use
  when accuracy matters more than latency/cost; skip otherwise.

**Colab reliability issues hit during this phase:**
- `ImportError: bitsandbytes` after a session restart — needed reinstalling and a full runtime restart (not just re-running `pip install`) for the package to register properly.
- `FileNotFoundError` on the just-created checkpoint folder — turned out to be a Google Drive sync delay, not a real loss; the folder existed, `os.listdir` just hadn't caught up yet.
- Multiple full runtime resets from hitting Colab's free-tier compute limit, losing in-memory results (`results`, `failures`, `results_v2`) that hadn't been saved to disk. **Lesson, now standard practice:** save anything expensive to regenerate (eval results, training datasets) to Google Drive immediately, and for long-running loops, checkpoint partial progress to disk every N iterations rather than only saving at the end.

---

## 7. Phase 6 — Schema Validation (Static AST Parsing)

**Motivation:** Even with schema in the prompt and retry logic, the model still sometimes hallucinates a column/table name that doesn't exist (e.g. `TS_age` instead of `Age`, `pet_type` instead of `PetType`). Rather than only catching this after a wasted database call, added a pre-execution check.

**What it does:** Parses generated SQL into a structured form (via the `sqlglot` library — a real SQL parser, not regex, since regex can't reliably handle nested queries, joins, and function calls) and checks every table/column reference against the real schema before ever executing the query.

**Why `sqlglot` over regex:** SQL is a structured, potentially nested language (subqueries, joins, functions wrapping columns). Regex is a flat pattern matcher with no concept of scope or nesting — it can be patched to handle more cases but never robustly. A real parser (`sqlglot`) builds the actual query structure, so alias resolution (`T1` → `singer`) and column ownership are handled correctly by construction.

### Bugs found and fixed while building this, in order:

1. **Unqualified columns silently skipped** — when a query had no table alias (e.g. `SELECT TS_age FROM singer`, no `AS T1`), `sqlglot` returned an empty string for the column's table, which didn't match anything in the alias map, and the check was silently skipped via `continue`. **Fix:** added a fallback — if a column has no alias, check it against *all* tables in the query; only flag it if it matches none of them.

2. **Case sensitivity — columns** — schema stored `Age`, `Name`, `Country` (capitalized); generated SQL used lowercase `age`, `name`, `country`. Plain Python `in` is case-sensitive, so valid SQL was being wrongly flagged. **Fix:** lowercase both sides before comparing.

3. **Case sensitivity — tables** — same bug, missed in a different spot: `SELECT * FROM Pets` was flagged as an unknown table because `t.name` (original case) was checked against `real_table_names_lower` (already-lowercased) without lowercasing `t.name` first.

4. **Double-quoted strings misparsed as columns** — SQLite allows `WHERE country = "France"` (double quotes for what's actually a string value), but standard SQL treats double quotes as *identifiers* (column/table names). `sqlglot` parsed `"France"` as a column reference, which of course didn't exist in the schema, and got wrongly flagged. Tried specifying `read="sqlite"` first — didn't fully fix it, since SQLite's own double-quote handling is context-dependent (identifier if it matches a real name, string otherwise) and a static parser can't replicate that without already knowing the schema. **Fix:** preprocess the SQL to convert double-quoted segments to single-quoted before parsing (`normalize_quotes()`), sidestepping the ambiguity entirely, since your model never legitimately double-quotes a real identifier.

5. **Ambiguous-but-valid columns across joins** — tested deliberately: a column name that exists on *multiple* tables in a join (e.g. `Stadium_ID` on both `stadium` and `concert`). Confirmed this correctly passes validation (doesn't falsely reject it) — the validator's job is "does this identifier exist anywhere relevant," not "resolve exactly which table was meant," which is a deliberately narrower, achievable scope.

**Tested with `pytest`** — 7 tests covering all of the above bugs, all passing, run in under a second. This locks in every fix so a future change can't silently reintroduce one of these bugs.

---

## 8. Phase 7 — Ensemble / Majority Voting

**Motivation:** The existing retry logic returns the *first* candidate that's valid and executes — but "runs without error" isn't the same as "is correct." A better signal: generate several candidates, and see which *answer* (execution result) the model agrees with itself on most often. This is a standard technique called **self-consistency**.

**Also added — a runaway-join safety guard (`is_reasonable_query`):** During eval, the model occasionally generated a pathological, 40+ table self-join (e.g. repeating `JOIN treatments AS T39 JOIN treatments AS T40...` almost indefinitely). This caused the eval loop to hang for a very long time. Added a cheap upfront check — reject any candidate with more than a set number of tables (default 8) — *before* even attempting validation or execution.

**Also added — a query timeout in `execute_queries`** as a second, more general safety net, since a normal-looking query could in principle still hang for other reasons.

**Result on one example (France singer age query):** 5 sampled candidates, 3 of 5 agreed on the correct answer `(34.5, 25, 43)`; voting correctly selected it even though it wasn't the first candidate generated. Confirmed working on the exact original hallucination example from Phase 1 too — greedy alone would have produced `TS_age`, but validation + retry + voting together produced the correct query.

**Full 150-sample eval with validation + voting:** attempted multiple times, repeatedly interrupted by Colab's free-tier compute/runtime limits (including once after a runaway-join stall before the safety guard was added, and twice more from hitting the compute quota entirely, losing all in-memory progress each time). Added incremental checkpoint-saving (save `results_v2` to disk every 15 examples) to make future runs resilient to this. **Final number not yet confirmed as of this note.**

---

## 9. Phase 8 — Moving to a Real Project Structure (VS Code)

Everything above lived in Colab notebook cells and scratch `explore.py` calls. Restructured into four real Python modules, each with one clear responsibility:

- **`schema_validation.py`** — Is this SQL structurally valid against this schema? No model, no database — pure logic. Contains `parse_schema_string()` and `validate_sql()`. Fully unit-tested (`test_schema_validation.py`).

- **`db_runner.py`** — Runs SQL against a SQLite file safely, with a timeout so a runaway query can't hang the process. Contains `execute_queries()` and `compare_execution()`.

- **`model_utils.py`** — Talks to the model. Contains `format_schema()` and `generate_sql()` only — deliberately just generation, nothing else, so if the model or serving approach ever changes, only this file needs to change.

- **`inference.py`** — Combines the other three into full strategies. Contains `is_reasonable_query()` (the join-count safety guard), `generate_sql_with_retry()` (first-valid-wins strategy), `generate_candidates()` + `vote_on_candidates()` + `generate_sql_final()` (generate-many-and-vote strategy).

**Dependency direction, kept one-way to avoid circular imports:**
```
schema_validation.py   db_runner.py   model_utils.py
        \                   |               /
         \                  |              /
              inference.py (imports all three)
```

**Why this split:** each file answers exactly one question. Anything that *combines* generation, validation, or execution belongs in `inference.py`, not scattered into whichever file it happens to touch first. This also means `schema_validation.py` can be fully tested without any GPU or model access — which is exactly what happened in Phase 6.

---

## 10. Checkpoints — Summary Table

| Checkpoint | Description | Accuracy (150-sample) | Notes |
|---|---|---|---|
| `checkpoint-122` | Original fine-tune | 70.67% (106/150) | Baseline after retry logic added |
| `checkpoint-270` | + 26 contrastive examples (join/negation patterns) | 71.33% (107/150) | Aggregate wash, but fixed 7/44 targeted failures. **Currently in use.** |

---

## 11. Open Threads / Next Steps (as of Phase 8)

- **Full validation + voting eval (150-sample)** — interrupted repeatedly by Colab compute limits; rerun with incremental saving in progress as of the last session. Check `results_v2_checkpoint.jsonl` on Drive.
- **Full 1034-example eval** — never completed for any checkpoint; all accuracy numbers so far are from a 150-example random sample (seed=42), which has a real margin of error (~±7 points at n=150). Worth running the full set once a checkpoint is considered stable.
- **Remaining failure patterns (3, 4, 5 from Phase 3)** — schema confusion, spurious joins, and comparison-target errors were identified but not yet targeted with contrastive data the way patterns 1 and 2 were.
- **Roadmap beyond current scope** (deliberately not built yet, per a "build when actually needed" decision, not because they're unimportant):
  - Semantic layer (business term → SQL mapping) — needed once real user questions use jargon that doesn't map directly to column names.
  - RAG-based schema retrieval — needed once a schema is too large to fit in one prompt (current Spider schemas are small, so this isn't a real bottleneck yet).
  - Multi-dialect SQL support (Postgres/Snowflake/BigQuery) — needed once a customer requires a non-SQLite backend.
  - Full production hardening (Phase 0 security/tenant isolation, SOC 2, multi-agent architecture, MCP tool exposure, etc.) from the broader architecture plan — a multi-month, multi-engineer-scale roadmap; being deliberately sequenced against real need rather than built speculatively.

---

## 12. Lessons Worth Remembering

- **A 100% failure rate is a pipeline bug, not a model quality signal.** Always isolate and print raw output before assuming the model is at fault.
- **Silent `None`-swallowing is dangerous.** A function that catches an error and returns `None` instead of raising can turn a real bug into a confusing crash several layers away. Guard against `None` explicitly wherever it can occur.
- **Stale kernel state in notebooks causes real, hard-to-diagnose bugs.** When a function behaves nonsensically, check what's actually defined (`inspect.getsource()`) rather than trusting memory of what you last wrote.
- **Regex is fine for narrow, fixed-format input; a real parser is needed for anything structured and variable** (like arbitrary SQL).
- **Save expensive-to-regenerate results to disk immediately, and checkpoint long-running loops incrementally.** Free-tier compute environments can and will interrupt you without warning.
- **A small, narrow fix to training data can teach a real pattern without moving the aggregate number** — check targeted before/after comparisons, not just the overall score.
- **Explain every "why this tool/approach over that one" choice at the time it's made** — it's cheap to do in the moment and expensive to reconstruct later.

## Semantic Layer — Complete

Built and fully verified (`semantic_layer.py` + `model_utils.py` integration):
- `find_relevant_terms(question, db_id)` — detects known business terms
- `inject_semantic_context(question, db_id)` — formats matched terms
  into a prompt-ready text block
- Wired into `generate_sql()` in `model_utils.py`

Verified in Colab with an invented example term ("high performer" ->
Age < 30 AND country = 'France' in concert_singer schema):
- Question containing the term correctly generated SQL reflecting
  the injected definition
- Question NOT containing the term generated normal, unaffected SQL
  (confirms the empty-context guard works, no leakage)

Current limitation: `SEMANTIC_TERMS` is a hardcoded example dict, not
real business terminology — built to verify the mechanism, not
because a real need has appeared yet. Expand with real terms if/when
actual user questions surface jargon the schema doesn't cover.

---

## 13. Phase 9 — Live Database Connectivity (in progress)

**Motivation:** First item on the Deployment Readiness half of the roadmap — the product currently only ever queries Spider's static SQLite files. Nothing yet connects to an actual customer database. This phase is scoped narrowly to "connect, introspect, and safely execute against a live DB" — not to rewiring `inference.py`'s generation strategies to use it, which is a deliberately separate, later step.

**New/changed files, four incremental steps taken in this order (each building on the safety guarantee of the one before it):**

1. **`query_guard.py`** (new) — `guard_readonly(sql)`. Rejects anything that isn't a plain `SELECT`, checked two ways: first-keyword check (catches non-read statements outright) and a full-string disallowed-keyword scan (catches a `WITH ... AS (DELETE ... RETURNING *) SELECT ...` CTE that starts with `SELECT` but mutates data inside). Split into its own file rather than inlined into `db_runner.py` so it's independently unit-testable and reusable anywhere else generated SQL needs checking later (e.g. a future "preview before run" UI step). Read-only was chosen deliberately as the launch default — read/write can be added later as an opt-in, higher-trust tier.

   - **`test_query_guard.py`** (new) — pytest, matches the existing `test_*.py` style. Covers: plain/whitespace/case-insensitive SELECTs pass; INSERT/UPDATE/DELETE/DROP rejected; the disguised-DELETE-in-a-CTE case; empty string rejected.

2. **`db_runner.py`** (edited) — `execute_live()` now calls `guard_readonly()` before running anything (when `readonly=True`, the default), and the `timeout_seconds` parameter — previously accepted but never actually used — is now enforced via a `ThreadPoolExecutor` future with a timeout. Return shape changed from "rows or `None`" to `{"ok": bool, "rows"/"error": ...}`, so a caller (and eventually an API layer) can distinguish "ran successfully, zero rows" from "failed to run" — the old `None`-for-everything behavior couldn't. `execute_queries()` and `compare_execution()` (the SQLite eval-harness path) are untouched.

3. **`db_connection.py`** (edited), two changes:
   - `get_live_schema()` now returns columns with types, plus primary key and foreign keys per table (was previously just a flat list of column names). This is a breaking change to the return shape, made now specifically because nothing consumes the old shape yet — `schema_validation.py` and the semantic layer will need types/keys, not just names, once live schemas are wired into them.
   - `get_engine()` now sets `pool_pre_ping=True` and `pool_recycle=3600` (avoids handing out dead/stale connections), and adds a Postgres-specific server-side `statement_timeout` via `connect_args` (libpq's `options` arg) when the connection string is `postgresql://...`. Scoped to Postgres only, deliberately — MySQL, Snowflake, etc. each have their own timeout mechanism, and guessing wrong would silently do nothing rather than actually enforce a limit. This works alongside `execute_live`'s thread-based timeout, not instead of it: the thread timeout stops the app from waiting, this stops the query from running on Postgres's server at all.

4. **`schema_validation.py`** and **`inference.py`** (edited) — `validate_sql()` and `is_reasonable_query()` both hardcoded `sqlglot.parse_one(sql, read="sqlite")`. Added a `dialect="sqlite"` parameter to both (default unchanged, so the Spider eval harness and existing tests are unaffected) so a live engine's dialect can be passed in once live, non-SQLite schemas are actually being validated.

**Known follow-up, not yet done:** SQLAlchemy's dialect name and sqlglot's aren't always identical (SQLAlchemy: `"postgresql"`, sqlglot: `"postgres"`) — a small mapping dict will be needed when `db_connection.py`'s engine is actually plugged into `validate_sql`/`is_reasonable_query`, rather than passing `engine.dialect.name` straight through.

**Not yet done (explicitly deferred):**
- Wiring `execute_live` / `get_live_schema` into `inference.py`'s actual generation strategies — right now `generate_sql_final` etc. still only exercise the SQLite eval path.
- Credential storage for connection strings (plaintext today) — needs a real secrets approach before this touches a real customer DB, and will matter more once multi-tenant isolation (a separate roadmap item) is built.
- Timeout mechanisms for MySQL/Snowflake/BigQuery (only Postgres has server-side enforcement so far).

---

## 14. Phase 10 — Live Database Connectivity: Closed Out

Picked up exactly where Phase 9 left off: the three deferred items (credentials, schema-validation wiring, execution wiring) were finished today, closing out live database connectivity end-to-end.

**1. Credentials — `config.py` (new)**

`get_connection_string(env_var="DATABASE_URL")` reads the connection string from an environment variable instead of a hardcoded value, via `python-dotenv` loading a local (gitignored) `.env` file. Not a full secrets-manager — deliberately the standard baseline for a single dev with no customers yet, not a speculative build-ahead. `.env.example` added as a committed template. Requires adding `python-dotenv` to `requirements.txt` and confirming `.env` is in `.gitignore` (both manual, not code).

**2. `schema_validation.py` — live-schema-aware validation (edited)**

`validate_sql()` previously assumed one schema shape (the Spider string format). It now accepts a `live_schema` parameter — a dict from `get_live_schema()` — which takes priority over `schema_lookup`/`db_id` when provided, and made those two optional so live callers don't need to fabricate a fake `db_id`. A new `extract_column_names()` normalizer collapses all three schema shapes the codebase now produces (Spider string, old flat dict, live typed dict) down to what validation needs today — column existence, not yet types/joins.

Added alongside this: `get_sqlglot_dialect()` in `db_connection.py`, mapping SQLAlchemy dialect names to sqlglot's (they don't always match — `"postgresql"` vs `"postgres"`) — this was flagged as a follow-up in Phase 9 and became necessary the moment live validation was actually wired up.

Tested in `test_schema_validation.py`: normalizer on all three shapes, valid/unknown-column/unknown-table/join cases against a live schema, live_schema-takes-priority case, and the new `ValueError` when neither schema source is given. 9/9 passing.

**3. `model_utils.py` — live-schema-aware prompting (edited)**

`generate_sql()` had the same single-shape assumption as `validate_sql()` did, but for prompt-building instead of validation — `format_schema()` only knew the Spider string format. Added `format_live_schema()` (builds an equivalent prompt string from a live typed schema) and a `live_schema` parameter on `generate_sql()` with the same priority rule as `validate_sql`. This was the actual blocker preventing a live query from working end-to-end — validation could already check live SQL, but nothing could *generate* a prompt for a live schema in the first place.

**Known gap, not yet closed:** `inject_semantic_terms()` is keyed on `db_id`, and a live connection currently has no `db_id` assigned. Business-term injection silently does nothing for live-connected databases until each one gets an assigned `db_id` to key `semantic_terms.json` entries against. Not urgent (no live customer using semantic terms yet), but will surface as "why doesn't it know our business terms" the first time it matters.

**4. `inference.py` — executor abstraction (edited)**

Rather than duplicating the three generation strategies (`generate_sql_query_with_retry`, `generate_candidates`, `generate_sql_final`) into live/eval variants, added an `executor` parameter to each: a callable `(sql) -> {"ok": bool, "rows"/"error": ...}`. `_eval_executor(db_path)` adapts the existing `execute_queries` SQLite path to this interface; `_live_executor(engine, ...)` wraps `execute_live`. One code path serves both, rather than two that would inevitably drift.

Also changed: `voting_candidates()` now returns the full winning `{"sql", "result"}` dict instead of just the SQL string, and `generate_sql_final()` returns `{"sql": ..., "result": ...}` (result is `None` on the greedy-fallback path, when nothing validated and executed successfully). This was needed because `generate_candidates` already executes every candidate internally to vote on it — throwing that result away and making the caller re-run the winning query would mean hitting the database twice for no reason.

**Debugging note:** after this edit, `test_inference.py` initially failed with `db_path` still being a required positional argument and `voting_candidates` still returning a bare string — the edit hadn't fully landed in the actual file despite being sent. A full-file replacement (rather than another incremental patch) was used to remove any ambiguity about the file's actual state, since incremental edits across many turns in one session had gotten hard to track by eye. One follow-up round after that still surfaced a stale `generate_sql_final` (`TypeError: string indices must be integers, not 'str'` — the exact signature of a fallback branch still returning a bare string instead of a dict) — fixed once the full file was confirmed replaced. **Lesson:** when a file's been patched many times across a long session, a full-file replacement is more reliable than another targeted diff, and a `TypeError` on string-indexing a return value is a strong signal that a return-shape change didn't actually take.

Tested in `test_inference.py` (`monkeypatch`-based — stubs `generate_sql`/`validate_sql` so the orchestration logic is tested independently of the actual model): `voting_candidates` returns the full dict not just SQL; `generate_sql_final` returns `{"sql", "result"}` on success, falls back correctly (and never calls the executor) when nothing validates, picks the majority result correctly when candidates disagree; `_live_executor`/`_eval_executor` correctly wrap `execute_live`/`execute_queries` including the `None`-as-failure translation. 9/9 passing.

**Result: live database connectivity is done, end-to-end.** Connect (`db_connection.get_engine`, credentials via `config.py`) → introspect (`get_live_schema`, typed) → generate (`model_utils.generate_sql`, live-schema-aware prompting) → validate (`schema_validation.validate_sql`, live-schema-aware, dialect-correct) → safely execute (`db_runner.execute_live`, read-only-enforced, timed out) → vote (`inference.generate_sql_final`, executor-abstracted) → return SQL + answer together. First item on the Deployment Readiness roadmap, complete.

**Carried-forward gaps (unchanged from Phase 9, still real):**
- Semantic-layer term injection has no `db_id` path for live connections yet.
- Credential storage is env-var-based — fine for one dev, not yet multi-tenant-safe.
- Server-side query timeout enforcement is Postgres-only; MySQL/Snowflake/BigQuery still rely solely on the app-side thread timeout.

**Next roadmap item:** model serving as a persistent API service — `model`/`tokenizer` are still loaded manually into whatever script calls this; nothing runs as a standing service yet.

---

## 15. Phase 11 — Model Serving as a Persistent API (in progress)

**Motivation:** the second Deployment Readiness item. Everything so far loads `model`/`tokenizer` manually into whatever script or notebook calls it — nothing stands as a running service that an API layer (or anything else) can call without reloading the model from scratch each time.

**Stack decision:** FastAPI, deployed to a GPU-available host (not CPU-only). Chosen partly because FastAPI can double as the actual product API layer later (a separate, still-unbuilt roadmap item), not just a model-serving shim.

**Design, two new files:**

- **`model_loader.py`** (new) — loads the model/tokenizer once as a module-level singleton, with an explicit `load_model()` to trigger loading and `get_model_and_tokenizer()` to access it afterward. `get_model_and_tokenizer()` raises rather than lazily loading, so a route handler can never accidentally trigger a slow first-load mid-request.
- **`app.py`** (new) — the FastAPI service. Loads the model once via FastAPI's `lifespan` startup hook (not per-request). The `/generate` route wraps `inference.generate_sql_final`, run via `run_in_threadpool` — necessary because model generation is a blocking, GPU-bound call, and running it directly inside an `async def` route would stall FastAPI's single event loop for the full generation time, queuing up every other request (even a trivial `/health` check) behind it.

**Known gaps flagged at design time, not yet resolved:**
- `/generate`'s request shape currently only makes sense for the Spider eval `schema_lookup` (`question` + `db_id`) — not yet wired to accept a live database connection reference instead, which is what the actual product needs. Deliberately left as an open gap rather than gluing in eval-only code that would need ripping out immediately.
- No concurrency limit on GPU work — `run_in_threadpool` will run multiple `generate_sql_final` calls concurrently if requests overlap, but a single GPU usually serves one generation efficiently at a time. Not a problem solo, will matter once tested under concurrent load.

**Bug: `ValueError: Unrecognized model in ... Should have a model_type key in its config.json`**

Hit on first real load attempt, using `checkpoint-270`'s Hugging Face repo (`DilshanDev/llama-text2sql-v2-saas`) directly as `MODEL_REPO` with plain `AutoModelForCausalLM.from_pretrained`. Root cause: `checkpoint-270` was trained with QLoRA, so what got pushed to that repo is a **LoRA adapter** (`adapter_config.json` + adapter weights), not a full standalone model — an adapter has no `model_type` of its own because it isn't a complete model, it's a set of weight deltas meant to sit on top of the original base model.

**Fix:** load the base model first (`meta-llama/Llama-3.2-3B-Instruct` — matches NOTES.md's description of the base model, though not yet independently confirmed against the actual training notebook's exact `from_pretrained` call), then apply the adapter on top via `peft.PeftModel.from_pretrained(base_model, ADAPTER_REPO)`. `model_loader.py` updated accordingly. Two follow-ups noted, not yet resolved: confirm `peft` is listed in the serving-side `requirements.txt` (not only the training-side one), and confirm the exact base model repo string against the training notebook rather than assuming it.

**Credentials — HF token support added defensively.** Repo visibility (public vs. private) for `DilshanDev/llama-text2sql-v2-saas` wasn't confirmed, so rather than wait to find out, added optional token support now: `config.get_hf_token()` (mirrors `get_connection_string()`'s env-var pattern, but returns `None` instead of raising when unset, since a public repo needs no token at all). Threaded through `model_loader.py`'s `from_pretrained` calls. `.env.example` updated with an `HF_TOKEN` entry and a note that it's only required for private/gated repos. Separately flagged: `meta-llama/Llama-3.2-3B-Instruct` (the base model) is itself a **gated** repo on Hugging Face regardless of the adapter repo's visibility — it requires accepting Meta's license and a valid token to load at all, which makes `HF_TOKEN` non-optional in practice even if the adapter repo turns out to be public.

**In progress, not yet resolved as of this note:** after the LoRA fix, the base model began downloading (~6.43GB, first time on this machine) — slow connection, expected to take a long while. Confirmed this is normal (not an error) and that Hugging Face caches the download on disk, so it only needs to happen once per machine regardless of what happens afterward (a later error in adapter-loading or elsewhere wouldn't require re-downloading, only a genuinely interrupted/corrupted download would). Session paused here to let the download finish; whether the adapter then applies cleanly and the server actually reaches `Application startup complete` is unconfirmed.

**Still open going into next session:**
- Did `app.py` reach `Application startup complete`, or error after the download finished?
- Confirm the actual base model repo string against the training notebook.
- Confirm `DilshanDev/llama-text2sql-v2-saas`'s public/private status, and set a real `HF_TOKEN` in `.env` if needed (the base model being gated makes this likely necessary either way).
- The `/generate` request-shape gap (Spider `db_id` vs. a live connection reference) still needs a real design decision, not just a flag.

---

## 16. Phase 12 — Model Serving: Closed Out (long session, many bugs, real success at the end)

Picked up exactly where Phase 11 left off. This phase involved more distinct bugs than any prior phase — documented in the order encountered, since several are genuinely reusable lessons for future infra work, not just today's fixes.

**1. Hardware reality check — local GPU insufficient.**

Confirmed via `nvidia-smi`: local machine is a Windows laptop with an **RTX 2050, 4GB total VRAM**, ~700MB already claimed by OS/background processes. A 3B model even in 4-bit (~2–2.5GB weights) plus CUDA overhead plus generation buffers doesn't comfortably fit. Considered vLLM as an alternative — rejected for two reasons: it optimizes for concurrent-request throughput on datacenter GPUs (can use *more* baseline memory than plain `transformers` for a single request), and it has no native Windows support (Linux/WSL2 only), which was confirmed as the actual OS in use via traceback paths and `nvidia-smi`'s `WDDM` driver model.

**Decision:** serve from **Google Colab's free GPU tier** for now, tunneled out via **ngrok**, explicitly as a temporary measure — not the real deployment. Confirmed with the user that the code itself (`app.py`, `model_loader.py`, `config.py`'s env-var pattern) is already environment-agnostic, so the transition to a real paid GPU host later is "run the same files somewhere else," not a rewrite. No budget for a paid GPU currently; investigated AWS/GCP/Azure free tiers and confirmed none include an always-free GPU tier — only time-limited trial credits, none of which fit a $0-budget, indefinite-testing use case. Decision: use free trial-credit-free options (Colab/Kaggle) for testing, pay for a real host only once there are actual users.

**2. `peft` LoRA loading crash — `ValueError: Unrecognized model ... no model_type`.**

Covered in Phase 11 — confirmed fix (load base model, then `PeftModel.from_pretrained` on top) worked once actually tested.

**3. `peft` offload crash — `KeyError: 'base_model.model.model.model.embed_tokens'`.**

Hit once the base model actually loaded with `device_map="auto"` in bfloat16 — triggered because `accelerate` decided to offload some layers to CPU/disk (base model didn't fit in bfloat16 in available VRAM), and `peft`'s adapter-loading code has a known module-path bug when applying an adapter on top of an offloaded model.

**Fix:** switched to **4-bit quantization** (`BitsAndBytesConfig`, `nf4`, double quant, bfloat16 compute dtype) — chosen for two reasons, not one: it matches the original QLoRA training setup (base model was also 4-bit during training), and a 4-bit 3B model is small enough to plausibly avoid the offloading path that triggers the `peft` bug entirely.

**4. Quantization still insufficient — `ValueError: modules dispatched on CPU/disk`.**

Even at 4-bit, `accelerate` still needed to offload on the local RTX 2050 — confirmed this is a genuine hardware ceiling, not a config problem, once the local GPU's real free VRAM (~3.3GB after OS overhead) was checked against the model's real footprint. This confirmed the Colab decision from step 1 was correct rather than premature.

**5. `ngrok` auth — `ERR_NGROK_4018`, then quota — `ERR_NGROK_324`.**

`ngrok` now requires a free account + authtoken even for anonymous tunnels (policy changed since older tutorials). Separately, hit a "5 endpoint" cap from **stale tunnels** left behind by uncleanly-disconnected earlier Colab sessions (a Colab runtime dying doesn't get a chance to run tunnel cleanup code). Fixed by manually clearing stale tunnels from the ngrok dashboard, and adding `ngrok.kill()` before `ngrok.connect()` in code to reduce recurrence going forward (though this only cleans up the current process's tunnels, not ones orphaned by a prior uncleanly-ended session).

**Security note, twice repeated:** the real ngrok authtoken was accidentally pasted in plaintext into chat on two separate occasions during this session. Advised rotating it both times; user confirmed rotation and correctly commented `# rotated, not the leaked one` in the Colab cell on the second occurrence.

**6. Postgres connection — pooled vs. direct connection string.**

Neon's default connection string is **pooled** (routed through PgBouncer, hostname contains `-pooler`). `db_connection.py`'s Postgres `statement_timeout` (set via `connect_args={"options": "-c statement_timeout=..."}`, from Phase 9/10) is a session-level startup parameter that PgBouncer's transaction-pooling mode rejects outright — `ERROR: unsupported startup parameter in options: statement_timeout`. **Fix:** use Neon's **direct/unpooled** connection string instead of the pooled one. **Flagged as a real future gap, not fixed today:** if a real deployment later wants connection pooling (likely, for concurrent-user efficiency), `get_engine()` will need to either detect pooled connections and skip the startup-parameter timeout, or set the timeout a different way (e.g. a per-query `SET statement_timeout` instead of a connection-level parameter).

**7. `app.py`/`model_utils.py` request-shape redesign.**

Resolved the Phase 11 open gap: `/generate` no longer takes Spider's `db_id` — it targets a single live DB connection established once at startup (`lifespan` hook), matching the "connect once, not per-request" pattern already used for the model itself. `model_utils.py` gained `format_live_schema()` and a `live_schema` parameter on `generate_sql()`, mirroring the `live_schema` pattern already built into `validate_sql()` in Phase 10.

**8. Stale-file whack-a-mole — three separate bugs, one root cause.**

Manually uploading individual files to Colab (rather than `git clone`) meant several files silently stayed on old versions while local files had moved on:
- Old `app.py` still required `db_id` → `422 Field required`
- Old `model_utils.py` had no `live_schema` param → `'NoneType' object is not subscriptable`, then (after a partial fix) `generate_sql() got an unexpected keyword argument 'live_schema'`
- A genuinely new bug surfaced once files were current: **`inference.py` was passing `live_schema` to `validate_sql()` calls but not to the parallel `generate_sql()` calls in the same functions** — missed when the executor abstraction was wired through in Phase 10, never caught by `test_inference.py` because its monkeypatched `generate_sql` stub ignores all arguments regardless of what's passed (a real, acknowledged gap in that test's coverage).

**Fix, and the more important lesson:** stopped patching individual files in Colab entirely. Switched to `git push` locally, then `rm -rf` + fresh `git clone` in Colab for every subsequent change — eliminated this entire class of bug for the rest of the session. **Standing practice going forward: never manually re-upload individual files to Colab once a project has multiple interdependent files — always sync via git.**

**9. Silent server shutdown — background `subprocess.Popen` killed by unrelated cell interrupts.**

Running `uvicorn` as a foreground blocking cell made it impossible to test locally from another cell at the same time. Switched to `subprocess.Popen` in the background — but the server would silently receive `Shutting down` (uvicorn's standard SIGINT message) with no user-initiated Ctrl+C. **Root cause:** `subprocess.Popen` by default launches the child in the *same process group* as the notebook — interrupting any other cell (e.g. stopping a hung test request) can send SIGINT to the entire process group, killing the background server as collateral damage. **Fix:** `start_new_session=True` on the `Popen` call, isolating the server into its own session so other cells' interrupts can't reach it.

**10. CPU-only Colab runtime — multi-minute generation times, no error at all.**

After fixing the shutdown bug, a single `n=1` generation request took the full 300-second client timeout with no crash. Diagnosed by checking `nvidia-smi` *during* a live request — returned `command not found`, revealing the Colab runtime had **no GPU attached at all** (a CPU-only runtime type, confirmed via the Resources panel showing no GPU line, only RAM/Disk). `device_map="auto"` silently falls back to CPU with no warning or error when no GPU is visible, which is why nothing in the logs pointed here directly — everything "worked," just 10-20x slower than expected. **Fix:** Colab → Runtime → Change runtime type → T4 GPU. Confirmed fixed: a subsequent `n=1` request dropped from 300+ seconds (timeout) to ~5-9 seconds once genuinely running on GPU.

**11. `PydanticSerializationError: Unable to serialize unknown type: sqlalchemy.engine.row.Row`.**

First real `200`-adjacent failure once GPU + DB + generation all actually worked — `/generate` returned a bare `500 Internal Server Error` with no JSON detail, because the failure happened in FastAPI's response serialization, outside the route's `try/except`. Root cause: `execute_live`'s `result.fetchall()` returns SQLAlchemy `Row` objects, which pydantic can't serialize to JSON — unlike `execute_queries`'s sqlite3 path, which already returns plain tuples natively. This inconsistency between the two execution paths was never caught by tests, since `test_inference.py`'s fake executors return plain tuples directly rather than exercising real SQLAlchemy output. **Fix:** `execute_live` now converts rows to plain tuples (`[tuple(row) for row in result.fetchall()]`) at the source, so every caller downstream — live or eval — works with the same plain-Python-type contract.

**12. `address already in use` on restart.**

A leftover `uvicorn` process (from an earlier attempt in the same long session) was still holding port 8000. Fixed with `kill -9 $(lsof -t -i:8000)` before restarting — a routine restart-hygiene step given how many restarts this session involved, not a bug in the code itself.

**Result: first genuine end-to-end success.** `POST /generate` with `{"question": "average age of singers from France", "n": 5}` against the live Neon test DB returned `{"sql": "SELECT AVG(age) FROM singer WHERE country = 'France'", "result": [["29.0000000000000000"]]}` — correct query, correct answer (28+34+25 ÷ 3 = 29), in ~16 seconds on a genuinely GPU-backed Colab runtime. Notably, an `n=1` attempt on the same question had hallucinated a spurious join to a nonexistent `country` table (matching the exact "spurious/unnecessary join" failure pattern documented back in Phase 1 and Phase 3) — `n=5`'s self-consistency voting correctly filtered it out once more candidates were available to vote against it, which is the mechanism working exactly as designed under real conditions, not just Spider's eval set.

**Model serving as a persistent API service is done.** Second Deployment Readiness item closed out — end-to-end: model loads once (4-bit, LoRA adapter) → live DB connects once → both reused across requests → `/generate` validates, safely executes, self-consistency-votes, returns JSON → all confirmed against a real HTTP call, not just local Python calls.

**Carried-forward, explicitly not solved today:**
- Colab + ngrok is a temporary serving setup, not the real deployment — moving to a paid GPU host is the acknowledged next infrastructure step once there are real users to justify the cost.
- `get_engine()`'s Postgres `statement_timeout` still breaks on pooled connections — fine for now (direct connection in use), needs a real fix before pooling is used in production.
- No concurrency limit on GPU work in `/generate` (flagged in Phase 11, still unaddressed).
- `test_inference.py`'s monkeypatched stubs don't exercise real argument-passing between `generate_sql` and `validate_sql` calls, nor real SQLAlchemy row shapes — both gaps that let real bugs through to manual testing this session. Worth strengthening later, not urgent.

**Next roadmap item:** API layer / interface for the product — `app.py` already is a FastAPI service, so this is less "start from scratch" and more "expand `/generate` into a real API surface" (multiple endpoints, request/response contracts beyond a single route, etc.) — exact scope not yet defined.

---

## 17. Phase 13 — API Layer (in progress)

**Scoping decision, made deliberately before writing any code:** considered building support for multiple database connections as part of "API layer," but decided against it — multi-DB support is really what Multi-tenant data isolation (a separate, later roadmap item) requires, and designing it now, before auth/tenancy exist to give it real constraints, would mean designing it twice. Kept the single-connection-at-startup model as-is; scoped this phase narrowly to making what already exists genuinely API-shaped instead.

**1. `/schema` endpoint (new).**

Returns `get_live_schema()`'s output as-is (tables, columns with types, primary keys, foreign keys) rather than a separate "simplified for API" shape — deliberately, to avoid maintaining two schema representations that could drift out of sync. Real use cases identified for this: a future frontend showing available tables/columns before a user asks a question, debugging (checking what the live schema actually looks like without digging through Colab logs), and future transparency for a customer confirming their DB was introspected correctly. Confirmed working live — returns the `singer` table's full structure correctly.

**2. `/generate` failure-mode redesign — three distinct outcomes instead of one generic 500.**

Previously: any failure at all returned a bare `500` with `str(e)` as the detail — leaking raw internals (file paths, library specifics) and not distinguishing *why* something failed.

Redesigned into three cases:
- **`200`** — a real, validated, executed answer (unchanged from before).
- **`422`** — `generate_sql_final`'s fallback branch fired: every one of `n` candidates failed to validate and/or execute. Response includes `attempted_sql` (the final greedy attempt) so the caller has something to debug with, even though it wasn't trustworthy enough to execute.
- **`503`** — new: specifically when *every* candidate failed **because the database itself was unreachable** (not because the SQL was wrong). Distinguished from `422` because these mean different things to a caller — "rephrase your question" vs. "this isn't your fault, try again shortly."

Also replaced the generic-exception handler's `detail=str(e)` with a fixed, safe message — decided deliberately as a security habit to start now rather than retrofit later, even though today there's no real caller besides the developer testing manually.

**Implementing the 422/503 distinction required threading failure reasons further through the call chain than they previously went, since the information existed but was being discarded:**

- **`db_runner.py`** — `execute_live` now catches `sqlalchemy.exc.OperationalError` specifically (connection-level failures) before the generic `Exception` catch-all, and returns an `error_type` field (`"timeout"` / `"db_unavailable"` / `"query_error"`) alongside the existing `error` message, instead of every failure looking identical.
- **`inference.py`** — `generate_candidates` previously discarded *why* each candidate failed (`continue` with nothing recorded). Now tracks a `failure_reasons` list alongside `candidates`, and **returns a tuple `(candidates, failure_reasons)` instead of a plain list** — a real breaking change to its return type. `generate_sql_final` (the only caller) updated accordingly; if every recorded failure reason is `"db_unavailable"`, its fallback response now includes `"failure_reason": "db_unavailable"` so `/generate` can act on it.
- **`app.py`** — checks `output.get("failure_reason")` and returns `503` vs `422` accordingly.

**Test suite run after the change: 43/43 passing**, including with the `generate_candidates` return-type change — no regressions.

**Honest limitation, stated plainly rather than glossed over:** the `503` path is logically verified (covered by the passing test suite, which mocks the failure) but **not live-tested against a real database outage** — deliberately not attempted, since forcing Neon to actually become unreachable mid-request isn't easy or safe to simulate against the real test DB without deliberately breaking the connection string and paying the cost of reloading the model afterward. Flagged as a real gap rather than claimed as proven.

**Regression-tested the normal path after all changes** — same `n=5` question that succeeded in Phase 12 still returns a correct `200` after the sync. Confirmed the three-outcome redesign didn't disturb the working case.

**3. Real generation-quality gap surfaced by repeated manual testing — not a bug in today's work, but worth recording precisely.**

Running the *exact same* question (`"average age of singers from France"`, `n=5`) twice in a row: one run returned the correct answer (`29.0`); a second run returned an *incorrect but fully executable* answer (`32.0`) from a self-join (`JOIN singer AS T2 ON T1.country = 'France'`) that never actually links `T1`/`T2` by a shared key — schema-valid (real table, real columns), so it passes validation; executes without error, so it doesn't trigger either the `422` or `503` paths built today. Confirmed as sampling variance (`temperature=0.7` on the non-greedy candidates), not a code defect — a third run returned the correct answer again.

**Discussed directly: is this solvable, and by what?** Concluded it is *not* fully solvable — a fundamental characteristic of LLM generation, not a bug to patch away — but meaningfully reducible. Real candidate approaches, none built yet:
- **More targeted contrastive training data**, continuing Phase 5's proven method (26 hand-written pairs fixed 7/44 targeted failures then) — this time aimed specifically at self-joins missing an actual join-key condition.
- **A confidence threshold on self-consistency voting** — currently the majority wins even at something like 3-out-of-5; requiring a stronger majority (or returning "uncertain" below some threshold) would trade some answered questions for fewer *confidently wrong* ones.
- **A structural sanity check in `schema_validation.py`** — flagging a self-join with no actual shared key between the two sides, independent of any model retraining.
- **Completing the full 1034-example Spider eval**, still never done for any checkpoint (flagged as an open thread since Phase 8) — needed to know whether this is a 2% problem or a 20% problem, rather than reasoning from two manual repetitions of one question.

**Explicitly clarified: RAG-based schema retrieval does not address this.** RAG solves a different problem (a schema too large to fit in the prompt at all); the test schema here is a single table, so RAG has no bearing on this specific failure mode. Worth remembering so it isn't mistakenly treated as the fix later.

**Carried-forward, explicitly not solved today:**
- The `503` db-unavailable path needs a genuine live test at some point, not just a mocked one.
- The self-join/wrong-but-executable answer class of failure is unaddressed — noted above as a real, now concretely-demonstrated gap for the Generation Quality roadmap items, not something this phase's scope covered.
- Multi-DB connection support remains deliberately deferred to when Authentication/Multi-tenant data isolation are tackled, per this phase's opening scoping decision.

---

## 18. Phase 14 — The Full 1034-Example Spider Eval (finally completed)

Closed out a genuinely long-standing open thread — the full dev-set eval was flagged as never-completed as far back as Phase 8, with every prior accuracy number (checkpoint-122's 70.67%, checkpoint-270's 71.33%, the 72.00% with voting) coming from a 150-example or 50-example sample instead.

**Motivation for finally running it now:** the Phase 13 self-join incident (same question, same settings, correct one run and wrong-but-executable the next) raised the direct question "is this worth fixing via retraining?" — answerable only with a real failure rate across a representative dataset, not two repetitions of one question.

**Rebuilt the eval loop from scratch**, since the original lived only in ad-hoc Colab cells and predated the Phase 8 restructure into `inference.py`. Data sources (recovered from memory of the original approach, not rediscovered):
- `xlangai/spider` / `dreamerdeo/multispider`'s `dataset/spider/dev.json` — the 1034 dev questions + gold SQL.
- `richardr1126/spider-schema` — `schema_lookup`, same shape used throughout the project.
- `dreamerdeo/multispider`'s per-`db_id` `.sqlite` files, fetched on demand via `hf_hub_download`.

**New file: `eval_full.py`** — a checkpointed loop calling `inference.generate_sql_final` (the real, current production code path) against each dev example, scoring via `db_runner.compare_execution`. Checkpoints every 15 examples to a `.jsonl` file on Google Drive (not local Colab storage, which is wiped on disconnect) — resumable by design: `load_already_done()` reads already-scored indices from the checkpoint file and the loop skips them on restart, rather than resuming from an in-memory position that a disconnect would destroy.

**Added Weights & Biases logging**, on request — a new `get_wandb_api_key()` in `config.py` (same optional-env-var pattern as `get_hf_token()`), plus per-example logging of rolling (last-50) and cumulative accuracy. Used a **fixed run ID persisted to Drive** so a resumed run continues the same wandb run/chart rather than fragmenting into a new disconnected one each time it restarts.

**A genuine bug surfaced mid-run, handled safely by design:** `'<' not supported between instances of str and int'` — `compare_execution` (`db_runner.py`) and `voting_candidates` (`inference.py`) both used `sorted()` directly on raw SQL result rows, which crashes when a result set mixes types (e.g. a `NULL`/`None` next to a real number) that Python can't compare directly. The per-example `try/except` in `run_full_eval` caught this safely and the loop kept going — exactly as designed — but it meant 2 examples (433, 434) were scored `correct: False` purely due to the crash, not genuine model failure.

**Fix:** both functions now sort by each value's `str()` representation instead of the raw value — every value becomes comparable regardless of type, while still correctly grouping identical rows for the equality check.

**New file: `rerun_failed.py`** — rather than re-running the full 1034 examples again after the fix (a multi-hour cost for a 2-example bug), identifies exactly the checkpoint records with `generated_sql: None` (the crash signature) and re-scores only those. Confirmed working: both index 433 and 434 flipped to `correct: True` after the fix, at zero cost to the other 1032 already-correct results.

**Operational realities hit during the run, consistent with — and validating — the original NOTES.md lesson from Phase 6:**
- Colab's **daily** free-tier GPU quota (distinct from, and often tighter than, the per-session time limit) was hit partway through, around 4h34m/705 examples in. Resumed cleanly the next session via the checkpoint file with zero lost progress — the entire reason this architecture was built this way.
- Actual per-example pace observed: roughly 20-30 seconds at `n=5`, putting the true full-run cost at **6-8 hours of GPU time**, confirming the earlier estimate was in the right range.

**Final result: 673/1034 = 65.09% execution accuracy** (post-sort-fix; 64.89% before it, from the same run with 2 examples miscounted).

**This is meaningfully lower than every prior small-sample estimate:**

| Measurement | Accuracy |
|---|---|
| 150-sample (checkpoint-270, retry only) | 71.33% |
| 50-sample (+ validation + voting) | 72.00% |
| **Full 1034-sample (this run)** | **65.09%** |

**Real, useful takeaway:** small samples were optimistic — not wrong exactly, but not representative either. 65.09% was, at this point, treated as the trustworthy baseline — superseded later in this same phase, see below.

**Automated failure-breakdown analysis (`analyze_failures.py`, new file):** classified all 361 failures by re-executing each `generated_sql` against its real database (no GPU needed, just DB lookups) into three buckets: `no_valid_query` (fallback fired, nothing validated/executed), `invalid_sql` (a query exists but errors on execution), and `valid_but_wrong` (executes cleanly, wrong answer). Also added a heuristic (`is_suspected_spurious_self_join`, via `sqlglot`) specifically flagging the Phase 13 self-join pattern — same table joined to itself with no equality condition actually linking the two aliases.

**Result: `valid_but_wrong__other`: 298 (82.5% of failures, 28.8% of total); `invalid_sql`: 41 (11.4%/4.0%); `suspected_spurious_self_join`: 22 (6.1%/2.1%).**

**Important correction to the Phase 13 conclusion:** the self-join pattern that motivated running the full eval in the first place turned out to be a **small slice** — only 2.1% of the whole dataset. The dominant problem is the large, uncategorized 298-example `valid_but_wrong__other` bucket. Decided **not** to pursue a dedicated contrastive-training round for self-joins specifically, since that would target 2% of the problem while 28.8% sat unexamined — instead, moved to manual review of a sample from that bucket, the same method Phase 3 originally used (review a subset, look for recurring patterns by eye).

**Manual review (`sample_for_review.py`, new file — reproducible random sample via a fixed seed): 30 examples reviewed by hand, question/gold/generated SQL side by side.** Real findings, going well beyond what any automated heuristic could categorize:

- **Missing/skipped joins** (Phase 3 pattern #1, still present) — e.g. counting rows of the wrong table because a needed join was dropped entirely (indices 161, 222, 931), or skipping an intermediate junction table in a many-to-many relationship (402).
- **Negation errors** (Phase 3 pattern #2, still present, three distinct flavors) — answering the positive version of a negated question (62); applying `NOT IN` at the wrong grain so the condition becomes vacuously true (66); and one genuinely concerning case — hardcoding a guessed literal ID (`WHERE petid = 3`) instead of writing the real subquery-based filter (63), a hallucinated shortcut rather than a reasoning error.
- **Schema confusion between similar-purpose columns** (Phase 3 pattern #3, still present) — e.g. filtering on `Region` when the question meant `Continent` (725), or grouping by an ID column instead of the name column with the same conceptual meaning (446).
- **New pattern, not in the original Phase 3 list — misinterpreting an existing "stat" column as needing aggregation.** When a column is already named for the exact thing being asked (`tours`, `average`), the model sometimes wraps it in `COUNT`/`AVG` anyway instead of just selecting the column directly (459, 16).
- **New pattern — inconsistent handling of an implicit qualifier.** The same concept ("official" language) handled oppositely wrong in two different examples: adding an unrequested filter in one case (756), dropping a required one in another (754).
- **New pattern — case-sensitivity on string literals.** Logic otherwise correct, but a literal like `'math'` vs. the DB's actual `'Math'` silently returns an empty/wrong result under SQLite's case-sensitive string comparison (404, 361).
- **A smaller, murkier bucket of likely benchmark/gold ambiguity, not clearly model error** (960, 500, possibly 232/230) — e.g. "the youngest dog" reasonably means minimum age, but gold's own SQL uses `max(age)`; "most total injuries" reasonably could mean `SUM(killed)`, but gold uses `COUNT(*)`. Flagged as genuinely ambiguous rather than confidently miscounted either way.

**The most consequential finding, though, was about the eval methodology itself, not the model:** roughly **1 in 6** of the reviewed failures (128, 80, 417, 628, 617) were cases where the generated SQL was **logically identical to gold** — same values, same meaning — just with **SELECT columns in a different order**. `compare_execution`'s strict positional-tuple comparison was scoring these as wrong. This wasn't a rare edge case in the sample; it was one of the single most common "failure" reasons observed.

**Fix — `db_runner.py`'s `compare_execution` and `inference.py`'s `voting_candidates`, both changed to compare rows as order-independent value sets** (values stringified and sorted within each row, then rows sorted against each other) instead of strict positional tuples. Explicit, acknowledged trade-off: this can occasionally produce a **false positive** if two genuinely different result rows happen to contain the same values in a different arrangement — accepted as the right call given how much more common the column-order false-negative problem turned out to be.

**New file: `rescore_all.py`** — re-scores every already-completed example from the checkpoint file using the fixed comparison, without any GPU or regeneration — pure re-evaluation of already-generated SQL against the real databases.

**Result: 39 examples flipped (30 false→true, 9 true→false)** — confirming both sides of the trade-off actually happened in practice, not just in theory. Net **+21 correct**.

**Final, corrected result — the number to treat as the real baseline going forward: 694/1034 = 67.12%.**

| Measurement | Accuracy |
|---|---|
| 150-sample (checkpoint-270, retry only) | 71.33% |
| 50-sample (+ validation + voting) | 72.00% |
| Full 1034-sample, original strict comparison | 65.09% |
| **Full 1034-sample, corrected comparison** | **67.12%** |

**Genuinely useful outcome of this whole phase, worth stating plainly:** the original motivation (a single repeated question hallucinating a self-join) led to running the full eval, which led to discovering that self-joins were a minor issue but the eval methodology itself had a real, previously-unknown flaw inflating the failure count. Neither of those would have surfaced without doing the full run and the manual review — small-sample testing and automated-only analysis both would have missed it.

**Not yet done, the natural next step:** the manual-review patterns above (missing joins, negation, schema confusion, stat-column misinterpretation, case sensitivity, implicit-qualifier inconsistency) are now real, concrete, evidence-backed candidates for a second contrastive-training round, unlike the earlier self-join-only plan. Worth reviewing a larger sample (or all 298, time permitting) before finalizing which patterns to target, and worth deciding whether case-sensitivity specifically might be better solved as a `COLLATE NOCASE` normalization step rather than a training fix at all.

---

## 19. Phase 15 — API Layer, Continued (health check + request logging)

Picked back up on the API-layer work from Phase 13, deliberately choosing to finish it before starting Authentication — reasoning: auth's job is to control who can call which endpoints, and the endpoint surface was still evolving; better to let the API settle first than wire auth around something that might still change shape.

**Decision on ordering, made explicitly before building anything:** a real `/health` check first (fastest win, and directly addresses a real pain point from earlier sessions — multiple times this project genuinely couldn't tell "stuck" from "just slow"), then structured logging (foundational visibility, makes everything after easier to debug), then rate limiting last (matters once there's real traffic, not urgent solo). Rate limiting explicitly deferred, not built this session.

**1. Real `/health` check (edit to `app.py`).**

Previously a static `{"status": "ok"}` regardless of anything actually being true. Now verifies both the model and the live DB connection are genuinely usable — `_model_loaded_and_ready()` (calls `get_model_and_tokenizer()`, catches the `RuntimeError` it raises if the model never loaded) and `_db_reachable()` (a cheap `SELECT 1` against `_engine`, not a full query).

**Deliberate design choice: returns `200` even when degraded**, with `status: "degraded"` and per-component detail in the body, rather than a `503`. Reasoning: many monitoring/uptime tools treat any non-`200` as "the whole endpoint is down" without reading the response body — a `503` here would look identical to a full outage, when the server is actually up and specifically *able* to report what's wrong. Confirmed working live: `{"status":"ok","model":"ok","database":"ok"}`.

**2. Structured request logging (new file: `request_logger.py`; edit to `app.py`).**

Previously, the only record of `/generate` activity was whatever scrolled past in Colab's cell output — not searchable, not persistent, gone on runtime reset. Now every `/generate` call (success or failure) writes one JSON line to a file on Google Drive (same durable pattern as the eval checkpoints): timestamp, question, `n`, duration, status code, and either the generated SQL or an error tag.

**Deliberate omission, explained rather than just done:** the log does **not** include the query's actual result data (the returned rows) — only the SQL and metadata. Reasoning: a request log is for operational visibility (volume, latency, failure patterns), not long-term data storage; logging real customer query results by default, once real databases are involved, would be a privacy habit worth not starting in the first place. Can be added deliberately later if a genuine debugging need for it ever arises.

**Result: two of three planned API-layer items done this phase** (`/health`, request logging); rate limiting scoped but explicitly left for a future session, once real traffic or a public demo makes it more clearly worth building now rather than later.

**Next roadmap item, whenever picked back up:** Authentication — now has a more settled API surface to protect (`/generate`, `/schema`, `/health`), which was the whole reason this was sequenced before it.

## 20. Phase 16 — API Layer: Rate Limiting (closed out)

Last item of the three-part API-layer phase (`/health` and request logging closed out in Phase 15). Two separate protections, deliberately not conflated:

- **Request rate limiting** — protects against one client flooding the API.
- **GPU concurrency limiting** — protects the GPU itself, flagged as an open gap since Phase 11/12.

**Design decision: keyed by IP for now, not by API key.** Authentication doesn't exist yet, so IP is the only identity available. The key-extraction logic was deliberately isolated into its own function (`client_key()` in a new `rate_limit.py`) so that switching to per-API-key limiting once auth lands is a one-line change, not a rewrite of every route.

**1. Request rate limiting — `slowapi`.**

Chosen over hand-rolling a limiter (sliding-window/cleanup edge cases are a classic self-inflicted bug) and over a token-bucket algorithm (the industry favorite for bursty traffic, but overkill before there's real traffic to be bursty). Fixed/moving window via `slowapi` is the right amount of engineering for the current stage.

- New `rate_limit.py`: `client_key()` (IP-based), `limiter = Limiter(key_func=client_key, headers_enabled=True)`.
- New `config.get_rate_limit()` — same optional-env-var pattern as `get_hf_token()`/`get_wandb_api_key()`, but with a required default so the server runs with sane limits even when unconfigured.
- `/generate`: `10/minute` (GPU-costly). `/schema`: `60/minute` (cheap read). `/health`: unlimited, since uptime monitors must never be rate-limited.
- `429` responses carry a `Retry-After` header — the standard contract clients expect. Confirmed live: requests 1–60 to `/schema` returned `200`, request 61 returned `429` with `Retry-After: 60`.

**Bug hit: `"60/min"` instead of `"60/minute"`.** `slowapi` (via the `limits` package) only recognizes full unit words (`second`/`minute`/`hour`/`day`/`month`/`year`). An invalid unit string fails to parse — but `slowapi` **fails open by default** (`swallow_errors=True`), so the bad limit was silently never enforced rather than crashing loudly. All 61 test requests returned `200` with no error anywhere. **Fix:** corrected to `"60/minute"`; also set `swallow_errors=False` during testing so a bad limit string raises immediately instead of silently no-opping — reverted to the default (`True`) once confirmed working, since a rate-limiter config typo shouldn't take down the whole API for real customers.

**Colab/ngrok-specific gotcha:** behind a reverse proxy, every request arrives from the proxy's IP unless the app is told to trust forwarded headers — otherwise every client shares one rate-limit bucket. **Fix:** start uvicorn with `--proxy-headers --forwarded-allow-ips="*"`. Noted as a real, narrower fix needed for production: trusting `*` is fine only because the current proxy (ngrok) is the sole path in; a real deployment must scope this to the actual proxy's IP, not every source.

**2. GPU concurrency limiting — `asyncio.Semaphore`.**

Confirmed via `nvidia-smi` back in Phase 12 that this hardware serves one generation at a time efficiently — this was flagged as an unaddressed gap in Phase 11 and again in Phase 12, closed here.

- New `config.get_max_concurrent_generations()`, defaulting to `1` — matches the real hardware ceiling, becomes a real config knob only once serving moves to a host that can genuinely parallelize.
- New `rate_limit.generation_semaphore = asyncio.Semaphore(get_max_concurrent_generations())`.
- **Deliberately checks `.locked()` and rejects immediately with `503` + `Retry-After: 5`, rather than letting excess requests queue on `async with`.** A queued request could silently wait past a client's own timeout with no feedback — same "fail fast, tell the caller honestly" philosophy as the `422`/`503` split from Phase 13, applied to GPU load instead of DB/generation failure.

**Bugs hit while wiring this in, all found via manual two-request concurrency testing (not caught by any existing test):**

1. **`status_code==503` (comparison, not assignment)** in the semaphore-busy branch — an unnoticed typo that threw an unhandled `NameError` the instant the busy branch was reached, surfacing as a bare, header-less `500` in ~0.04s instead of the intended `503`. Caught only by actually triggering two concurrent requests and reading the real status code, not by inspection.
2. **A stale running process masked the fix twice in a row** — pushing the corrected code and re-cloning on Colab didn't matter because the *already-running* `uvicorn` process still had the old, broken module loaded in memory. Confirmed via `grep` on the file on disk (fix was present) versus the actual runtime behavior (fix wasn't). **Fix:** killed the stale PID (`lsof -i:8000`, `kill -9 <pid>`) and restarted fresh. **Lesson, worth generalizing:** a code fix that's confirmed on disk but still reproduces at runtime means the running process predates the fix — check for a stale process before re-diagnosing the "same" bug from scratch.
3. Applied `Popen`'s `stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True` to actually surface uvicorn's real tracebacks during debugging, rather than debugging blind from client-side status codes and timing alone — worth keeping as standard practice for any future background-server debugging session.

**Confirmed working, final state:** two near-simultaneous `/generate` calls at the default concurrency limit of 1 — one completes normally (~19-24s, `200`), the other returns almost instantly (~0.03-0.09s) with `503` and `Retry-After: 5`. Which of the two wins the semaphore is a genuine scheduling race between threads, not a bug — the shape of the result (one success, one fast-rejected) is what was being verified.

**Result: all three planned API-layer items are now done** (`/health`, request logging, rate limiting). API layer phase closed out.

**Carried forward:**
- Rate-limit storage is in-memory — resets on restart, and doesn't work across multiple server instances. The production answer is Redis; not needed yet at one Colab instance, but a real gap once there's more than one process serving traffic.
- IP-based keying is a known stopgap — revisit `client_key()` once authentication exists so limits and (eventually) tiers key off the API key/tenant, not the IP.
- No automated test yet for either the `429` or the GPU-busy `503` path — both were verified manually (Colab + real HTTP calls + threading), the same gap class as `test_inference.py`'s monkeypatched stubs not exercising real argument-passing (Phase 12). Worth a `TestClient`-based test with `generate_sql_final` mocked, so this doesn't require manually spinning up Colab and firing concurrent requests every time this code is touched.
No automated test yet... Closed — test_app.py covers both paths (429 on /schema, 503 on GPU-busy /generate, plus the 200/422/503(db-unavailable) generate outcomes), 5/5 passing.
- Production `--forwarded-allow-ips` should be scoped to the real proxy's IP, not `*`, once deployed for real.

## 21. Phase 17 — Authentication (in progress)

Up next per the roadmap, now that the API layer is fully closed out (Phase 16). Scoped as **API keys**, not JWT/OAuth login — the product is an API, not something end users sign into, and an API key doubles as the tenant identity that rate limiting, multi-tenant isolation, and billing will all need regardless, so building it first lets those reuse it rather than each inventing their own identity concept later.

**Design decisions made, with reasoning:**

- **API keys over JWT/OAuth or an auth-as-a-service provider (Auth0/Clerk).** JWT/OAuth is the right tool for a product with user logins (signup, password reset, sessions) — not yet needed here. Auth-as-a-service is reasonable later but adds a new dependency and cost before there are real users to justify it. API keys are the smallest thing that actually protects the API today, and the standard pattern for developer-facing APIs (Stripe, OpenAI, Anthropic all work this way).
- **Keys stored as SHA-256 hashes, never the raw key.** A database leak then exposes nothing usable. Looked up via direct indexed equality (`WHERE key_hash = ?`), not a loop of comparisons.
- **Not bcrypt/scrypt/argon2.** Those defend against brute-forcing low-entropy, human-chosen passwords. A 256-bit random key has no meaningful brute-force surface already, so a slow hash only adds latency to every authenticated request for no real security gain. SHA-256 is the standard choice here — same approach Stripe and GitHub use.
- **`hmac.compare_digest` for any direct key-vs-hash comparison** (used in `verify_api_key`, exercised in tests) — plain `==` short-circuits on the first mismatched byte, leaking a timing side-channel; constant-time comparison closes that.
- **`t2s_live_` prefix on generated keys**, plain text, not part of the secret. Lets a human or an automated secret-scanner (e.g. GitHub push-protection) recognize a leaked key by shape, and leaves room for a future `t2s_test_` sandbox tier without changing the generation function's structure.
- **Postgres (a separate Neon database), not DynamoDB, for the `api_keys`/`tenants` tables** — discussed and decided deliberately, not by default. The data is inherently relational (a tenant has many keys; usage/billing will need to roll up per tenant), which is exactly what a relational database is built for and what DynamoDB would require denormalizing around. DynamoDB remains genuinely worth learning, but on a workload that actually fits its strengths — **earmarked for the rate-limit store later** (a per-key counter, read/written at high frequency, no relations needed), replacing the in-memory storage flagged as a production gap back in Phase 16.
- **Separate control-plane database, apart from customer data** — a credential leak or bug in one database can't expose the other.

**Schema (`tenants`, `api_keys`):**
- `tenants`: `id`, `name`, `created_at`.
- `api_keys`: `id`, `tenant_id` (FK), `key_hash` (`UNIQUE`, indexed), `created_at`, `revoked_at` (nullable timestamp, not a boolean) — a timestamp records *when* a key was revoked, useful for later auditing ("was this key valid at the time of that request?"), which a plain `is_active` flag can't answer.
- No raw-key column anywhere, by design.

**`auth.py` — three small, pure functions, built and manually verified first (no DB needed):**
- `generate_api_key()` — `secrets.token_urlsafe(32)` (256 bits), not `random` (predictable) or `uuid4` (not documented as cryptographically secure) — `secrets` is Python's purpose-built CSPRNG.
- `hash_api_key()` — SHA-256, reused both at key creation and at lookup time.
- `verify_api_key()` — constant-time comparison; used directly in tests and anywhere a raw key is compared against one already-known hash.

**`create_key.py`** — a manual onboarding script (`python create_key.py "Tenant Name"`): creates the tenant row, generates a key, stores only its hash, and prints the raw key exactly once — the only moment it exists outside the client's hands. Tested successfully; tenant and hashed key confirmed inserted via direct `SELECT` against the control-plane DB.

**`require_api_key` — the FastAPI dependency wired into `/generate` and `/schema`:**
- Reads the key from the `X-API-Key` header (via `Header(...)` on an `x_api_key` parameter) — the conventional header for static API keys, as opposed to `Authorization: Bearer`, which is the convention for OAuth/JWT tokens. Matching the header convention to the auth type actually in use, rather than defaulting to `Authorization`, was a deliberate choice.
- `lookup_tenant()` hashes the incoming key and does a single indexed `WHERE key_hash = :key_hash AND revoked_at IS NULL` query — the revocation check lives in the query itself, not as a separate post-lookup condition in Python, so there's no code path where a revoked key could slip through by a downstream check being forgotten.
- Returns `tenant_id` (not just a boolean) via FastAPI's `Depends` injection — making the tenant's identity available to every protected route now, which rate limiting and billing will need next.
- Missing or invalid key → `401`. `/health` deliberately stays unauthenticated, since uptime monitors shouldn't need a key.
- Control-plane engine is a module-level singleton, matching the existing `_engine` pattern in `app.py` — created once, reused across requests.

**Not yet done / open as of this wrap-up:**
- Manual `curl` verification of the three cases (no key → `401`; wrong key → `401`; real key → `200`) — written but not yet run.
- No automated test yet for `require_api_key` — a real gap given `test_app.py` already exists and this is exactly the kind of security-critical path worth covering there, the same reasoning that drove writing tests for the rate-limit paths in Phase 16.
- `client_key()` in `rate_limit.py` still keys on IP, not yet switched to the now-available `tenant_id` — this was the explicit reason `client_key` was isolated into its own function back in Phase 16, and auth landing is what unblocks it.
- Key rotation/revocation workflow — the `revoked_at` column exists, but nothing yet sets it (no "revoke a key" script or endpoint).
- `app.py`'s other routes (none currently besides `/generate`/`/schema`/`/health`) and any future endpoints will need the same `Depends(require_api_key)` treatment as a matter of course.

**Next steps, in order:** run the `curl` verification; write `test_app.py` coverage for `require_api_key` (missing/invalid/revoked/valid key); then decide whether to switch `rate_limit.py`'s `client_key()` to tenant-based limiting before or after multi-tenant isolation, since that's the next roadmap item after auth closes out.

## 22. Phase 18 — Product Shape Clarified: Pivot from API-First to End-User Website

A direct conversation about "should auth be JWT/OAuth, since this is production SaaS?" surfaced that the actual planned product differs from what the earlier phases (13 onward) were built assuming.

**What was assumed through Phase 17:** an API-first product — other startups integrate `/generate` into their own backends. API keys are the industry-standard fit for that shape (Stripe/OpenAI/Twilio-style), which is why Phase 17 built hashed API-key auth first.

**What the product actually is:** an end-user-facing website. A person logs in, connects *their own* database, types a natural-language question, and sees results directly in the site's interface. There is no other company's backend calling this API — the caller is always a human in a browser.

**Why this changes the architecture, not just the auth mechanism:**

1. **JWT/OAuth moves from "a later learning phase" to "required, primary infrastructure."** Every action on the site belongs to a logged-in person, so session/login handling isn't optional or secondary — it's the main authentication path. API-key auth, built in Phase 17, isn't wasted: it remains valid for an optional secondary "call our API directly" path a user could enable later, but it's no longer the primary gate.

2. **"Tenant" was modeled wrong.** Phase 17 modeled a tenant as a company with an API key. In this shape, the tenant *is* the logged-in user. Multi-tenant isolation and user accounts collapse into one piece of work rather than two sequential phases.

3. **The single global DB connection in `app.py` doesn't fit anymore.** `_engine`/`_live_schema` were built once at server startup for one fixed customer database (correct for the API-first assumption — one company, one DB, configured once via `.env`). In the real shape, each logged-in user connects their *own*, different database. This needs to become per-user state, not a startup-time singleton — a real rework, not a small patch.

4. **User-supplied database credentials are a bigger security surface than anything built so far.** `config.py`'s `.env`-based pattern is fine for *your own* credentials (DB, HF token, wandb key) — it was never meant to hold *other people's* database passwords. Storing those needs real encrypted secrets handling (e.g. envelope encryption via a KMS), flagged now as its own roadmap item rather than folded quietly into "per-user connections."

**Decision: re-sequence the roadmap rather than bolt the new pieces onto the old plan.** User accounts + login (JWT/OAuth) is now the next phase, ahead of finishing tenant-based rate limiting (which depended on a tenant model that no longer matches the product) and ahead of the originally separate multi-tenant-isolation phase (now merged with user accounts, since they're the same concept in this shape). A new "Product Surface" roadmap section was added for the actual website itself (login screen, connect-a-database flow, query input, results view) — work that wasn't previously tracked at all because the API-first plan didn't need a frontend as core product.

**Nothing already built is thrown away:** `auth.py`'s hashing/constant-time-comparison functions, the `api_keys`/`tenants` schema, and the rate-limiting/concurrency work all remain valid pieces — they're repositioned (API keys: secondary/optional; tenant concept: reused for the new per-user model) rather than discarded.

## 23. Phase 19 — User Accounts + JWT Login (in progress)

Follows directly from Phase 18's pivot: the product is an end-user-facing website, not an API-first product, so login is now core, primary infrastructure rather than a later learning extension. Deliberately scoped small — password login only first; OAuth, email verification, and multi-DB connections are explicitly later steps of this same phase, not dropped.

**Schema decision: `users` table built minimal and strict, not pre-built for later features.**

```sql
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`password_hash` is `NOT NULL` and there's no `email_verified_at` column yet, even though both will be needed once OAuth/email-verification land. Deliberate: every user right now *does* have a password, so `NOT NULL` lets the database itself reject a bug that tried to insert a passwordless row, rather than silently allowing one. Loosening a constraint later (`ALTER COLUMN ... DROP NOT NULL`, adding a new column) is a one-line, no-downtime migration; tightening one after real data exists requires a backfill first. Starting strict and loosening later is the cheaper direction, so there's no benefit to front-loading structure for features that don't exist yet.

**Password hashing: `passlib` + `bcrypt`, not the SHA-256 used for API keys.** A real, important distinction, not just "use a different function because it's a different kind of secret": an API key is 256 bits of true randomness with no brute-force-able structure, so a fast hash (SHA-256) is correct and a slow one would only add latency for no security benefit. A human password is the opposite — low-entropy and guessable — so a deliberately *slow*, tunable hash (`bcrypt`) is what makes a stolen `users` table expensive to crack rather than instant. `CryptContext(schemes=["bcrypt"], deprecated="auto")` was chosen over calling `bcrypt` directly because `deprecated="auto"` gives a built-in path to upgrade to a stronger scheme later (e.g. `argon2`) without a manual rehash-everything migration — `passlib` can verify old hashes with the old scheme while hashing new ones with the new scheme.

**Bug hit: `ValueError: password cannot be longer than 72 bytes` on a short, ordinary password.** Not a real length issue — a known compatibility bug between `passlib` and `bcrypt` 4.x, which changed an internal version-detection interface that `passlib`'s backend misreads, miscounting password length on essentially any input. **Fix:** pinned `bcrypt==4.0.1` in both `requirements.txt` and `requirements-colab.txt`. Worth remembering as its own class of lesson (alongside the Phase 8 `bitsandbytes` issue): a library-pairing version bug can look exactly like a user-input error, and the fix is a version pin, not a code change.

**JWT: `PyJWT`, `HS256`, 60-minute expiry, no refresh token yet.**
- `create_access_token(user_id)` — uses the standard `sub` (subject) and `exp` claims rather than custom field names, so the token is interoperable with any standard JWT tool, not just this codebase's own code.
- `decode_access_token(token)` — returns `None` on any failure (expired, tampered, malformed) via a broad `except jwt.PyJWTError`, rather than letting exceptions leak to the caller; the caller (the next step's `require_user` dependency) only needs a yes/no.
- `exp` enforcement is handled automatically by `PyJWT` during `decode()` — no manual timestamp comparison needed.
- 60 minutes is a starting default, not derived from any real requirement yet; a refresh-token mechanism is a legitimate, explicitly deferred later addition, not an oversight.
- New required secret: `JWT_SECRET`, same optional-env-var-via-`config.py` pattern as `DATABASE_URL`/`HF_TOKEN`, generated once via `secrets.token_urlsafe(32)` and added to `.env`/`.env.example`.

**New file `auth_routes.py` — `/signup` and `/login` endpoints, mounted on `app.py` via `include_router`.**
- `EmailStr` (pydantic) validates email format at the request-parsing boundary, before any database touch.
- `/login` returns the identical `401` message regardless of whether the email doesn't exist or the password is wrong — a deliberate choice to avoid letting an attacker enumerate which emails have real accounts, a well-known information-leak pattern in login endpoints.
- `/signup` checks for an existing email and returns `409` on collision, otherwise inserts and returns a token immediately (sign up and be logged in, in one step) — no email verification gate yet, by design, since that's a later step.
- Both reuse `get_control_plane_engine()` from `auth.py` unchanged — `users` lives in the same control-plane Neon database as `tenants`/`api_keys`, no new connection logic needed.

**Local testing friction, not yet resolved as of this wrap-up — two separate issues surfaced:**

1. **Windows PowerShell's `curl` is an alias for `Invoke-WebRequest`**, with an entirely different argument syntax (`-H`/`-d` don't work as they do in real `curl`/bash/Colab) — not a bug, just a platform mismatch worth remembering for any future local-testing instructions on this machine. `Invoke-RestMethod` with a PowerShell hashtable piped through `ConvertTo-Json` is the more idiomatic equivalent, and parses the JSON response back into a usable object automatically.

2. **The real blocker: `app.py`'s `lifespan` unconditionally calls `load_model()` and connects to the live customer DB on every startup — including for testing endpoints (`/signup`, `/login`) that touch neither.** Since Phase 12 confirmed the local Windows machine's GPU (RTX 2050, 4GB) can't actually serve the model, attempting to run `uvicorn app:app` locally for pure auth testing likely hangs or fails before the server ever starts listening, which is why `Invoke-RestMethod` couldn't connect at all — nothing was there to connect to.

**Proposed fix, not yet confirmed:** gate the model/DB loading behind a `SKIP_MODEL_LOAD` env var in `lifespan`, so auth-only endpoints can be tested locally and quickly without Colab or a GPU at all — a real, useful separation now that auth and generation are genuinely independent concerns of the system.

**Not yet done / open as of this wrap-up:**
- Confirm whether a uvicorn process was actually running locally (`netstat -ano | findstr :8000`) — not yet checked.
- Apply the `SKIP_MODEL_LOAD` gate and retest `/signup`/`/login` locally.
- `require_user` — the FastAPI dependency that reads the JWT from a protected route and returns the logged-in user's `id` (mirrors `require_api_key`'s shape) — not yet written.
- OAuth (Google/GitHub), email verification, and `db_connections` (multi-DB per user) — all explicitly deferred to later steps of this same phase, not forgotten.

**Next step:** resolve local testing (apply the `SKIP_MODEL_LOAD` gate, confirm `/signup`/`/login` work end-to-end), then write `require_user` and protect a route with it.