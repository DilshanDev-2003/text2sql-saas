# Text2SQL SaaS

A text-to-SQL system: given a natural-language question and a database schema, it generates correct SQL. It is built around a fine-tuned Llama 3.2 3B model, with a schema-validation and self-consistency layer that catches and corrects common failure modes before an answer is returned. It runs against either a static evaluation database (SQLite/Spider) or a live database (SQLAlchemy), and is served as a persistent FastAPI service with API-key and JWT/OAuth authentication.

## Status

Actively in development. The generation pipeline (fine-tuned model, schema validation, majority-vote consistency checking) is built and tested, with **67.12% execution accuracy** on the full Spider dev set. Live database connectivity, the API layer (schema endpoint, health check, request logging, rate limiting, GPU concurrency guard), API-key authentication, password signup/login with JWT, Google OAuth login, and fail-fast startup validation are all built and covered by a 76-test suite.

**Product direction:** an end-user website where a person logs in, connects their own database, asks questions in natural language, and sees results. The backend foundations (accounts, login, the layered architecture) are in place; per-user database connections and the frontend are next. See [Roadmap](#roadmap).

## How it works

1. A request reaches `POST /generate` (`app/api/routes/generate.py`). It passes the rate limiter and API-key check, then a GPU concurrency guard that rejects excess requests immediately with `503` instead of queuing them.
2. If the question uses a known business term, its SQL meaning is injected into the prompt (`semantic_layer.py`). The schema comes from the live database, introspected once at startup.
3. The model, loaded once at startup, generates candidate SQL.
4. Each candidate is checked against the real schema (`schema_validation.py`), which catches hallucinated tables and columns before any query runs.
5. Surviving candidates are executed through a pluggable executor, either against a SQLite eval file or a live database with read-only enforcement and a timeout (`query_guard.py`).
6. The SQL whose *result* the most candidates agree on wins (self-consistency voting), and its SQL and result are returned as JSON. Failures return `422` (no valid query) or `503` (database unreachable or GPU busy).

**Authentication:** programmatic callers use an `X-API-Key` header (keys are stored only as SHA-256 hashes). People use `POST /signup` and `POST /login` (bcrypt-hashed passwords, JWT access tokens) or Google sign-in via `GET /auth/google/login`. `GET /me` returns the authenticated user.

**Startup:** before loading the model, the server validates its configuration (required environment variables, database reachability, control-plane tables, and that the generation database is not the control plane) and fails with one readable message listing every problem.

## Project structure

```
app/
├── core/       config, rate_limit, request_logger, startup_checks
├── auth/       security (hashing, JWT), dependencies (API key / user), routes, oauth, oauth_routes, users
├── db/         connection (engine + schema introspection), runner (execution), query_guard (read-only)
├── services/   model_loader, model_utils, schema_validation, semantic_layer, inference
├── api/        routes/{generate,schema,health}.py, schemas.py
└── main.py     app composition: lifespan, middleware, routers
scripts/        create_key.py, eval/ (offline evaluation tooling)
migrations/     001_control_plane.sql
conftest.py     test environment defaults
test_*.py       test suite (run from the project root)
```

| Layer | Responsibility |
|---|---|
| `app/core` | Cross-cutting concerns with no business logic: configuration from environment variables, rate limiting, request logging, startup validation. |
| `app/auth` | Everything about identity. `security.py` holds pure functions with no database or web framework; `dependencies.py` holds the database-backed lookups and FastAPI dependencies. |
| `app/db` | Database access only: engines, schema introspection, safe execution, read-only enforcement. |
| `app/services` | Product logic: model loading, prompting, schema validation, semantic layer, generation strategies. |
| `app/api` | Thin FastAPI route handlers. |

`scripts/eval/` holds the full-dev-set evaluation tooling (checkpointed eval loop, re-scoring, failure analysis, manual-review sampler) and is deliberately outside `app/`, since the running API never imports it. Model training lives in a separate Colab notebook (GPU required). See `NOTES.md` for the full development history.

## Setup

Local development (tests, auth, schema work; no GPU needed):

```bash
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`. The main variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | The database the model queries (a customer database, **not** the control plane) |
| `CONTROL_PLANE_DATABASE_URL` | Your own database for users, API keys, and OAuth identities |
| `JWT_SECRET`, `SESSION_SECRET` | Separate signing secrets (generate each with `python -c "import secrets; print(secrets.token_urlsafe(32))"`) |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth client (optional `GOOGLE_REDIRECT_URI`) |
| `HF_TOKEN` | Hugging Face token (the base model is gated) |
| `WANDB_API_KEY` | Optional, for eval logging |
| `RATE_LIMIT_GENERATE`, `RATE_LIMIT_SCHEMA`, `MAX_CONCURRENT_GENERATIONS` | Optional tuning |

Create the control-plane schema by running `migrations/001_control_plane.sql` against the control-plane database, then issue an API key:

```bash
python scripts/create_key.py "Tenant Name"
```

The key is printed once and only its hash is stored.

To test authentication without a GPU, skip model loading:

```bash
SKIP_MODEL_LOAD=1 uvicorn app.main:app --port 8000
```

Serving the model needs a GPU with enough VRAM and currently runs on Colab (local hardware is insufficient). In a Colab notebook: clone the repo, `pip install -r requirements-colab.txt`, load the variables above from Colab Secrets into `os.environ`, then run `uvicorn app.main:app --host 0.0.0.0 --port 8000` (expose it with `ngrok` for external testing). The code is environment-agnostic, so moving to a dedicated GPU host needs no code changes.

## Running tests

```bash
pytest -v
```

76 tests covering schema validation, query execution, the read-only guard, inference orchestration (with model generation mocked, so no GPU is needed), the semantic layer, all API routes including rate-limit and GPU-busy paths, authentication (signup, login, JWT, OAuth with Google mocked), and startup validation.

## Evaluation methodology

Accuracy is measured by **execution accuracy**: the generated SQL and the gold SQL are both run against the real database, and their *results* are compared, not the raw SQL text, and not sensitive to which order the SELECT columns came back in. This catches cases where differently written SQL produces the same correct answer, and cases where similar-looking SQL produces a wrong one.

Evaluated against the full [Spider](https://yale-lily.github.io/spider) text-to-SQL benchmark dev set (1034 examples).

| Measurement | Accuracy |
|---|---|
| 150-example sample (checkpoint-270, retry only) | 71.33% |
| 50-example sample (+ validation + voting) | 72.00% |
| **Full 1034-example dev set (checkpoint-270)** | **67.12%** |

The full-dataset number is the trustworthy baseline; small samples turned out to be optimistic. See `NOTES.md` (Phase 14) for the failure-pattern analysis and a real bug in the evaluation comparison logic that was found and fixed along the way.

## Roadmap

Built incrementally, driven by need rather than upfront completeness.

### Generation Quality
- [x] Fine-tuned base model
- [x] Execution-accuracy evaluation harness
- [x] Schema validation (pre-execution hallucination guard)
- [x] Self-consistency (majority-vote) generation
- [x] Semantic layer (business terminology to SQL mapping)
- [ ] Second contrastive-training round targeting the failure patterns found in the full-eval manual review (missing joins, negation, schema confusion, stat-column misinterpretation, case sensitivity)
- [ ] RAG-based schema retrieval (for large schemas)
- [ ] Multi-dialect SQL support beyond Postgres

### Accounts and Security
- [x] API-key authentication (hashed, constant-time verification)
- [x] Password signup/login with JWT
- [x] Google OAuth login
- [x] Fail-fast startup validation
- [ ] Email verification (also unlocks safe linking of OAuth and password accounts)
- [ ] Rate limiting on `/signup` and `/login`
- [ ] Per-user database connections: credentials stored encrypted, engines created per connection and cached
- [ ] Encrypted secrets storage for user-supplied database credentials (KMS-style)
- [ ] Read-only database role and per-connection table allowlists for the generation connection
- [ ] GitHub login

### Deployment Readiness
- [x] Live database connectivity (SQLAlchemy, any engine)
- [x] Model serving as a persistent API service
- [x] API layer: schema endpoint, error handling (422/503), real health check, request logging, rate limiting, GPU concurrency guard
- [ ] Shared rate-limit store (DynamoDB or Redis) for multi-instance deployment
- [ ] Versioned database migrations with Alembic
- [ ] Usage metering and billing
- [ ] Deployment infrastructure (hosting, uptime, scaling)

### Product Surface
- [ ] Frontend web interface: login, connect-a-database flow, query input, results view
- [ ] Query history
- [ ] Account and usage page