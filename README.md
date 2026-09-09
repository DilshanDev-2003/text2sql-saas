# Text2SQL SaaS

A text-to-SQL system: given a natural language question and a database schema, generates correct SQL. Built around a fine-tuned Llama 3.2 3B model, with a schema-validation and self-consistency layer to catch and correct common failure modes before returning an answer. Can run against either a static evaluation database (SQLite/Spider) or a live, real database (SQLAlchemy, any supported engine).

## Status

Actively in development. Core generation pipeline (fine-tuned model + schema validation + majority-vote consistency checking) is built and tested. Live database connectivity — connecting to, introspecting, validating against, and safely querying a real database — is also built and tested. Broader production concerns (persistent model serving, multi-tenant security, RAG-based schema retrieval, multi-dialect SQL beyond Postgres) are deliberately not yet built — see [Roadmap](#roadmap).

## How it works

1. A question + database schema go into the fine-tuned model. If the question uses a known business term (e.g., domain-specific jargon not present in the schema), its real SQL meaning is injected into the prompt first (`semantic_layer.py`). The schema itself can come from either a static lookup (Spider eval) or a live database connection (`db_connection.py`).
2. The model generates candidate SQL.
3. Each candidate is checked against the real schema (`schema_validation.py`) — catches hallucinated column/table names before ever touching a database. Works against either schema source.
4. Surviving candidates are executed (`db_runner.py`) via a pluggable executor — either safely against a SQLite eval file with a timeout, or against a live database with both read-only enforcement and a timeout (`query_guard.py`).
5. If multiple candidates were generated, the most self-consistent answer wins — the SQL whose *result* the most candidates agree on, not just the first one that happened to run (`inference.py`). The winning SQL and its result are both returned, so nothing needs to be re-executed.

## Project structure

| File | Responsibility |
|---|---|
| `schema_validation.py` | Checks if generated SQL only references real tables/columns. Works against a static (Spider) schema or a live database schema. No model needed either way. |
| `db_runner.py` | Executes SQL safely: against a SQLite file for eval (with a timeout), or against a live SQLAlchemy connection (read-only enforced, timed out). |
| `db_connection.py` | Creates a SQLAlchemy engine for any supported database and introspects its live schema (columns, types, primary keys, foreign keys). |
| `query_guard.py` | Rejects any SQL that isn't a plain, safe `SELECT` — the read-only enforcement used before executing generated SQL live. |
| `config.py` | Reads database credentials from environment variables (`.env` locally) instead of hardcoding them. |
| `model_utils.py` | Talks to the fine-tuned model — prompt formatting (for either schema source) and generation only. |
| `semantic_layer.py` | Maps business terminology to real SQL logic, so questions using jargon the schema doesn't cover still resolve correctly. |
| `inference.py` | Combines the above into full generation strategies (first-valid-wins retry, and generate-many-then-vote), against either a static eval database or a live one. |

Model training and full evaluation runs live in a separate Colab notebook (GPU required); the modules above are local, GPU-free application code.

## Setup

Local development (schema validation, execution, tests — no GPU needed):

```bash
pip install -r requirements.txt
```

To connect to a live database, copy `.env.example` to `.env` and fill in a real connection string:

```bash
cp .env.example .env
# then edit .env and set DATABASE_URL
```

Training/inference (Colab, GPU required):

```bash
pip install -r requirements-training.txt
```

## Running tests

```bash
pytest -v
```

Covers `schema_validation.py`, `db_runner.py`, `query_guard.py`, and `inference.py`'s logic (with the model generation step mocked out, so no GPU is needed to run the test suite) — including the live-database code paths, exercised with mocked schemas and executors rather than a real connection.

## Evaluation methodology

Accuracy is measured by **execution accuracy**: the generated SQL and the gold SQL are both run against the real database, and their *results* are compared — not the raw SQL text. This catches cases where differently-written SQL produces the same correct answer, and catches cases where similar-looking SQL produces a wrong one.

Evaluated against the [Spider](https://yale-lily.github.io/spider) text-to-SQL benchmark dev set.

| Checkpoint | Accuracy (150-example sample) |
|---|---|
| Base fine-tune | 70.67% |
| + targeted contrastive training data | 71.33% |

See `NOTES.md` for the full development history, every bug hit along the way, and how each was diagnosed and fixed.

## Roadmap

Being built incrementally, driven by actual need rather than upfront completeness:

### Generation Quality
- [x] Fine-tuned base model
- [x] Execution-accuracy evaluation harness
- [x] Schema validation (pre-execution hallucination guard)
- [x] Self-consistency (majority-vote) generation
- [x] Semantic layer (business terminology → SQL mapping)
- [ ] RAG-based schema retrieval (for large schemas)
- [ ] Multi-dialect SQL support beyond Postgres (Snowflake, BigQuery, MySQL)

### Deployment Readiness (required before launch — not deferred)
- [x] Live database connectivity (SQLAlchemy-based, any engine)
- [ ] Model serving as a persistent API service (not notebook-based) — **up next**
- [ ] API layer / interface for the product
- [ ] Authentication
- [ ] Multi-tenant data isolation
- [ ] Semantic-layer term authoring (usable without writing Python)
- [ ] Usage metering / billing
- [ ] Deployment infrastructure (hosting, uptime, scaling)