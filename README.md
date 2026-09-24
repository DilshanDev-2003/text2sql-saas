# Text2SQL SaaS

A text-to-SQL system: given a natural language question and a database schema, generates correct SQL. Built around a fine-tuned Llama 3.2 3B model, with a schema-validation and self-consistency layer to catch and correct common failure modes before returning an answer. Can run against either a static evaluation database (SQLite/Spider) or a live, real database (SQLAlchemy, any supported engine), and is servable as a persistent API, not just as scripts.

## Status

Actively in development. Core generation pipeline (fine-tuned model + schema validation + majority-vote consistency checking) is built and tested. Live database connectivity and model serving as a persistent API are both built and confirmed working end-to-end against a real database. The API layer has a live-schema endpoint, a real health check, and structured request logging; rate limiting is scoped but not yet built. Broader production concerns (authentication, multi-tenant security, RAG-based schema retrieval, multi-dialect SQL beyond Postgres) are deliberately not yet built — see [Roadmap](#roadmap).

## How it works

1. A question comes in via the `/generate` API endpoint (`app.py`). If it uses a known business term (domain-specific jargon not present in the schema), its real SQL meaning is injected into the prompt first (`semantic_layer.py`). The schema itself comes from a live database connection, introspected once at startup (`db_connection.py`) — or, for evaluation, a static Spider lookup. The same live schema is also available directly via `GET /schema`.
2. The model — loaded once at startup, not per-request (`model_loader.py`) — generates candidate SQL.
3. Each candidate is checked against the real schema (`schema_validation.py`) — catches hallucinated column/table names before ever touching a database.
4. Surviving candidates are executed (`db_runner.py`) via a pluggable executor — either safely against a SQLite eval file with a timeout, or against a live database with both read-only enforcement and a timeout (`query_guard.py`).
5. If multiple candidates were generated, the most self-consistent answer wins — the SQL whose *result* the most candidates agree on, not just the first one that happened to run (`inference.py`). The winning SQL and its result are both returned as JSON; every `/generate` call is also logged (question, duration, outcome — not result data) for operational visibility.
6. `GET /health` reports whether the model and live database connection are both genuinely usable, not just whether the process is running.

## Project structure

| File | Responsibility |
|---|---|
| `app.py` | The FastAPI service. Loads the model and connects to the live database once at startup; exposes `POST /generate`, `GET /schema`, and `GET /health`. |
| `model_loader.py` | Loads the fine-tuned model (base model + LoRA adapter, 4-bit quantized) once as a singleton, for reuse across every request. |
| `request_logger.py` | Writes one structured JSON line per `/generate` call (question, duration, status, outcome) to a durable log file — not the query's result data, deliberately. |
| `schema_validation.py` | Checks if generated SQL only references real tables/columns. Works against a static (Spider) schema or a live database schema. No model needed either way. |
| `db_runner.py` | Executes SQL safely: against a SQLite file for eval (with a timeout), or against a live SQLAlchemy connection (read-only enforced, timed out, results normalized to plain Python types for JSON serialization). |
| `db_connection.py` | Creates a SQLAlchemy engine for any supported database and introspects its live schema (columns, types, primary keys, foreign keys). |
| `query_guard.py` | Rejects any SQL that isn't a plain, safe `SELECT` — the read-only enforcement used before executing generated SQL live. |
| `config.py` | Reads database credentials, the Hugging Face token, and (optionally) a Weights & Biases API key from environment variables (`.env` locally) instead of hardcoding them. |
| `model_utils.py` | Talks to the fine-tuned model — prompt formatting (for either schema source) and generation only. |
| `semantic_layer.py` | Maps business terminology to real SQL logic, so questions using jargon the schema doesn't cover still resolve correctly. |
| `inference.py` | Combines the above into full generation strategies (first-valid-wins retry, and generate-many-then-vote), against either a static eval database or a live one. Result rows are compared order-independently (both across rows and within each row), so logically identical answers in a different column order aren't miscounted as different. |
| `eval_full.py`, `rerun_failed.py`, `rescore_all.py`, `analyze_failures.py`, `sample_for_review.py` | Full-dev-set evaluation tooling: a checkpointed, resumable eval loop; targeted re-scoring of specific examples; failure categorization; and a reproducible manual-review sampler. See `NOTES.md` Phase 14 for the full story, including a real eval-methodology bug this tooling found and fixed. |

Model training and full evaluation runs live in a separate Colab notebook (GPU required). For now, the API itself also runs on Colab (see [Setup](#setup)) — local hardware isn't sufficient to serve the model; the code is written to be environment-agnostic, so moving to a dedicated GPU host later needs no code changes, only a different place to run it.

## Setup

Local development (schema validation, execution, tests — no GPU needed):

```bash
pip install -r requirements.txt
```

To connect to a live database, copy `.env.example` to `.env` and fill in a real connection string and (if the model repo is gated/private) a Hugging Face token:

```bash
cp .env.example .env
# then edit .env and set DATABASE_URL and, if needed, HF_TOKEN
```

Running the API — Colab, GPU required (see `NOTES.md` Phase 12 for the full setup story, including known gotchas):

```bash
pip install -r requirements-colab.txt
```

Then, inside a Colab notebook: set `DATABASE_URL`/`HF_TOKEN` as environment variables, launch `uvicorn app:app --host 0.0.0.0 --port 8000`, and expose it via `ngrok` for external testing. A local, non-Colab GPU host with enough VRAM (roughly 4GB+ free, more with headroom) can run the same command directly, no ngrok needed.

## Running tests

```bash
pytest -v
```

Covers `schema_validation.py`, `db_runner.py`, `query_guard.py`, and `inference.py`'s logic (with the model generation step mocked out, so no GPU is needed to run the test suite) — including the live-database code paths, exercised with mocked schemas and executors rather than a real connection.

## Evaluation methodology

Accuracy is measured by **execution accuracy**: the generated SQL and the gold SQL are both run against the real database, and their *results* are compared — not the raw SQL text, and not sensitive to which order the SELECT columns came back in. This catches cases where differently-written SQL produces the same correct answer, and catches cases where similar-looking SQL produces a wrong one.

Evaluated against the full [Spider](https://yale-lily.github.io/spider) text-to-SQL benchmark dev set (1034 examples).

| Measurement | Accuracy |
|---|---|
| 150-example sample (checkpoint-270, retry only) | 71.33% |
| 50-example sample (+ validation + voting) | 72.00% |
| **Full 1034-example dev set (checkpoint-270)** | **67.12%** |

The full-dataset number is the trustworthy baseline — small samples turned out to be optimistic. See `NOTES.md` Phase 14 for the full breakdown, including a manual review of failure patterns (missing joins, negation errors, schema confusion, case sensitivity, and others) and a real bug in the evaluation comparison logic itself that was found and fixed along the way.

See `NOTES.md` for the full development history, every bug hit along the way, and how each was diagnosed and fixed.

## Roadmap

Being built incrementally, driven by actual need rather than upfront completeness:

### Generation Quality
- [x] Fine-tuned base model
- [x] Execution-accuracy evaluation harness
- [x] Schema validation (pre-execution hallucination guard)
- [x] Self-consistency (majority-vote) generation
- [x] Semantic layer (business terminology → SQL mapping)
- [ ] Second contrastive-training round targeting patterns found in the full-eval manual review (missing joins, negation, schema confusion, stat-column misinterpretation, case sensitivity)
- [ ] RAG-based schema retrieval (for large schemas)
- [ ] Multi-dialect SQL support beyond Postgres (Snowflake, BigQuery, MySQL)

### Deployment Readiness (required before launch — not deferred)
- [x] Live database connectivity (SQLAlchemy-based, any engine)
- [x] Model serving as a persistent API service (not notebook-based)
- [ ] API layer / interface for the product — `/schema`, error handling (422/503), a real `/health` check, and request logging are done; rate limiting is scoped but not yet built
- [ ] Authentication — **up next**
- [ ] Multi-tenant data isolation
- [ ] Semantic-layer term authoring (usable without writing Python)
- [ ] Usage metering / billing
- [ ] Deployment infrastructure (hosting, uptime, scaling)