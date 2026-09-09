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