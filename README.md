# Text2SQL SaaS

![tests](https://github.com/DilshanDev-2003/text2sql-saas/actions/workflows/tests.yml/badge.svg)

A text-to-SQL service: a person logs in, connects their own PostgreSQL database, asks a question in natural language, and gets back the generated SQL and its result. It is built around a fine-tuned Llama 3.2 3B model, with a schema-validation and self-consistency layer that catches and corrects common failure modes before an answer is returned, and a security-first design for handling other people's database credentials.

## Status

Actively in development. The generation pipeline (fine-tuned model, schema validation, majority-vote consistency checking) reaches **67.12% execution accuracy** on the full Spider dev set. The end-to-end flow works and has been verified against a real database on a GPU: account signup and login (password and Google), email verification, per-user encrypted database connections, and SQL generation against the user's own database. A 221-test suite runs in CI on every push.

Not yet built: the web frontend, a cap on result size, per-connection table allowlists, real email delivery, and production hosting. The plan is to release a small, safe v1 early rather than finish every roadmap item first; see [v1 Scope](#v1-scope) and [Roadmap](#roadmap).

## How it works

1. **Connect a database.** `POST /connections` validates the connection string (public hosts only, TLS required, only allowlisted parameters), opens a test connection, reads the schema, encrypts the string with AES-GCM, and saves it. The engine is kept in a bounded cache.
2. **Ask a question.** `POST /generate` takes `{connection_id, question, n}`. It passes the rate limiter and the JWT check, confirms the connection belongs to the caller, and loads the engine and schema from the cache (rebuilding and revalidating if needed).
3. **Generate.** A GPU concurrency guard rejects excess requests immediately with `503` instead of queuing them. The model, loaded once at startup, generates `n` candidate queries (1 to 10).
4. **Validate and execute.** Each candidate is checked against the real schema (`schema_validation.py`), which catches hallucinated tables and columns before any query runs. Survivors run read-only with a timeout (`query_guard.py`, `statement_timeout`).
5. **Vote.** The SQL whose *result* the most candidates agree on wins (self-consistency), and its SQL and result are returned as JSON. Failures return `422` (no valid query) or `503` (customer database unreachable or GPU busy).

Every `/generate` call appends one JSON line (question, duration, status, SQL; never result rows) to the request log at `REQUEST_LOG_PATH`. Logging failures never fail a request.

## Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /signup`, `POST /login` | none (rate limited) | Password accounts; returns a JWT |
| `GET /auth/google/login`, `GET /auth/google/callback` | none | Google sign-in |
| `POST /auth/verify-email`, `POST /auth/resend-verification` | none (resend rate limited) | Email verification |
| `GET /me` | JWT | The authenticated user |
| `POST /connections` | JWT, **verified email** | Add a connection (rate limited) |
| `GET /connections`, `DELETE /connections/{id}` | JWT | List (metadata only) and remove |
| `GET /connections/{id}/schema` | JWT | The connection's introspected schema |
| `POST /generate` | JWT | Generate SQL and run it on the user's connection |
| `GET /health` | none | Model and control-plane status |

## Security model

- **Credentials at rest.** Connection strings are encrypted with AES-GCM, bound to the owning user, with key versioning for rotation. They are never returned by the API and never logged. A KMS-backed key store is planned.
- **Outbound safety (SSRF).** Users supply hostnames, so every connection string passes one validator: PostgreSQL only; TLS required; only `sslmode` and `channel_binding` accepted as parameters (libpq would otherwise honor `host=`, `options=`, and certificate paths); every resolved address must be public (private, loopback, link-local, and metadata ranges are rejected, including IPv4-mapped IPv6); and the engine connects to the *validated address*, which defeats DNS rebinding. Error messages never include the connection string.
- **Query safety.** Only plain `SELECT` statements run (`query_guard.py`), with a statement timeout and read-only sessions by default. The real boundary is a read-only database role, which users are asked to create for this product; a per-connection table allowlist is planned.
- **Accounts.** bcrypt password hashing, short-lived JWTs, email verification required before connecting a database, no account enumeration on login or resend, lowercase email normalization with a database-level unique index, and protection against account pre-hijacking when linking Google sign-in. Signup, login, resend, and connection creation are rate limited.
- **Known limits.** `sslmode=require` encrypts but does not verify the server certificate; result rows are not yet capped; rate limits are per IP and in memory; the encryption key lives in the environment.

## Project structure

```
app/
├── core/       config, encryption, rate_limit, request_logger, startup_checks, email_sender
├── auth/       security, emails, dependencies, routes, verification, oauth, oauth_routes, users
├── db/         connection (engines, schema introspection), connection_safety (SSRF validation),
│               runner (execution), query_guard (read-only)
├── services/   model_loader, model_utils, schema_validation, semantic_layer, inference,
│               connections (create/list/delete/get engine), connection_cache
├── api/        routes/{generate,connections,health}.py, schemas.py, errors.py
└── main.py     app composition: lifespan, middleware, routers
scripts/        create_key.py (legacy API keys), eval/ (offline evaluation tooling)
migrations/     001_control_plane, 002_email_verification, 003_lowercase_emails, 004_db_connections
.github/workflows/tests.yml   CI: runs the test suite on every push and pull request
conftest.py     hermetic test environment (fake secrets, pinned limits, limiter reset)
test_*.py       test suite (run from the project root)
```

| Layer | Responsibility |
|---|---|
| `app/core` | Cross-cutting concerns with no business logic: configuration, encryption, rate limiting, request logging, startup validation, the email-sending interface. |
| `app/auth` | Everything about identity. `security.py` and `emails.py` are pure functions; `dependencies.py` holds the database-backed lookups and FastAPI dependencies. |
| `app/db` | Database access only: engines, schema introspection, connection-string safety, safe execution, read-only enforcement. |
| `app/services` | Product logic: model loading, prompting, schema validation, generation strategies, and the connection service and cache. |
| `app/api` | Thin FastAPI route handlers and the mapping from service errors to HTTP status codes. |

`scripts/eval/` holds the full-dev-set evaluation tooling and is deliberately outside `app/`, since the running API never imports it. API-key authentication code remains (`require_api_key`, `create_key.py`) but no route currently uses it; per-user API keys may return later. Model training lives in a separate Colab notebook (GPU required). See `NOTES.md` for the full development history.

## Setup

Local development (tests, accounts, connections; no GPU needed):

```bash
pip install -r requirements.txt
cp .env.example .env
```

`requirements.txt` does not install PyTorch (install it separately; CI uses the CPU wheel). Fill in `.env`:

| Variable | Purpose |
|---|---|
| `CONTROL_PLANE_DATABASE_URL` | Your own database for users, connections, and verification tokens |
| `JWT_SECRET`, `SESSION_SECRET` | Separate signing secrets, at least 32 characters (`python -c "import secrets; print(secrets.token_urlsafe(32))"`) |
| `ENCRYPTION_BACKEND`, `ENCRYPTION_KEYS`, `ENCRYPTION_KEY_VERSION` | Connection-string encryption. Generate a key with `python -c "import os, base64; print('1:' + base64.b64encode(os.urandom(32)).decode())"`. Back it up: losing it makes saved connections unreadable. Everything sharing a control-plane database must use the same key |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth client (optional `GOOGLE_REDIRECT_URI`) |
| `HF_TOKEN` | Hugging Face token (the base model is gated) |
| `WANDB_API_KEY` | Optional, for eval logging |
| `EMAIL_BACKEND` | Defaults to `console` (development only: it logs verification links) |
| `FRONTEND_URL` | Base URL used in verification links |
| `REQUEST_LOG_PATH` | Request log file; defaults to `logs/request_log.jsonl` (set to a Drive path on Colab) |
| `RATE_LIMIT_GENERATE`, `RATE_LIMIT_SIGNUP`, `RATE_LIMIT_LOGIN`, `RATE_LIMIT_RESEND`, `RATE_LIMIT_CONNECTIONS_CREATE`, `RATE_LIMIT_CONNECTIONS`, `MAX_CONCURRENT_GENERATIONS` | Optional tuning (defaults: 10/minute, 10/hour, 10/minute, 5/hour, 10/hour, 60/minute, 1) |

Run the files in `migrations/` in order (`001` to `004`) against the control-plane database.

To exercise accounts and connections without a GPU, skip model loading (this also skips the startup checks):

```bash
SKIP_MODEL_LOAD=1 uvicorn app.main:app --port 8000
```

On Windows PowerShell:

```powershell
$env:SKIP_MODEL_LOAD = "1"
uvicorn app.main:app --port 8000
```

Serving the model needs a GPU and currently runs on Colab. In a notebook: `%cd /content`, clone the repo, `pip install -r requirements-colab.txt`, load the variables above from Colab Secrets into `os.environ` (with the **same** `ENCRYPTION_KEYS` as local), then run `uvicorn app.main:app --host 0.0.0.0 --port 8000`. At startup the server validates its configuration (required variables, encryption setup, control-plane tables) and fails with one message listing every problem, before loading the model.

## Running tests

```bash
pytest -v
```

221 tests covering schema validation, query execution and the read-only guard, inference orchestration (model generation mocked, so no GPU is needed), the semantic layer, every API route including rate-limit and GPU-busy paths, authentication (signup, login, JWT, Google OAuth mocked), email verification and normalization, encryption, connection-string safety, the connection service and cache, request logging, and startup validation. The suite is hermetic: `conftest.py` supplies fake secrets and pins configuration, so it behaves the same on a laptop and in CI.

## Evaluation methodology

Accuracy is measured by **execution accuracy**: the generated SQL and the gold SQL are both run against the real database, and their *results* are compared, not the raw SQL text, and not sensitive to the order of the SELECT columns.

Evaluated against the full [Spider](https://yale-lily.github.io/spider) text-to-SQL benchmark dev set (1034 examples).

| Measurement | Accuracy |
|---|---|
| 150-example sample (checkpoint-270, retry only) | 71.33% |
| 50-example sample (+ validation + voting) | 72.00% |
| **Full 1034-example dev set (checkpoint-270)** | **67.12%** |

The full-dataset number is the trustworthy baseline; small samples turned out to be optimistic. Spider schemas are small, so this benchmark says little about large real-world databases. See `NOTES.md` (Phase 14) for the failure-pattern analysis and a real bug in the evaluation comparison that was found and fixed.

## v1 Scope

The plan is to release a small, safe v1 early, learn from real use, and keep building in parallel with other work. Because users hand over database credentials, the security items are launch requirements, not polish.

### Required for v1
- [x] Accounts: password signup/login (JWT), Google sign-in, email verification
- [x] Lowercase email normalization, rate limits on `/signup` and `/login`, CI
- [x] Per-user database connections: encrypted credentials, SSRF-safe validation, cached engines, verified-email gate
- [x] `/generate` against the user's own connection (verified end to end on a GPU)
- [ ] Cap on result rows returned from customer databases
- [ ] Read-only database role guidance and a per-connection table allowlist
- [ ] Large-schema handling: the table allowlist plus a prompt-size guard with a clear error (RAG schema retrieval only if alpha databases exceed that limit)
- [ ] Minimal frontend: login, connect a database, ask a question, see **the generated SQL together with the result**
- [ ] Accuracy limits disclosed to users (67% execution accuracy on the Spider benchmark)
- [ ] Real email delivery (AWS SES) or invite-only signup
- [ ] Deployment: always-available GPU model hosting, HTTPS, monitoring

### Hardening before the public stage
- [ ] KMS-backed encryption keys
- [ ] Rate limits keyed by user instead of IP; shared rate-limit store for multiple instances
- [ ] Per-account login throttling; equalize `/login` timing for unknown emails
- [ ] Connection-pooler support (per-transaction settings instead of startup options)
- [ ] Startup checks refusing the console email backend and short secrets in deployed environments
- [ ] Log retention policy and privacy statement (request logs contain questions and generated SQL)
- [ ] Production proxy settings so rate limits see real client IPs; egress rules blocking private ranges

### After v1
Second contrastive-training round, RAG schema retrieval (if not needed sooner), multi-dialect SQL, billing and metering, GitHub login, query history, account page, Alembic migrations, static type checking.

### Release stages
1. **Private alpha:** a handful of people I know, free, using sample or non-production copies of their data.
2. **Invite-only beta:** real databases, but only through read-only roles.
3. **Public release:** after metering and billing exist and demand justifies them.

## Roadmap

### Generation Quality
- [x] Fine-tuned base model, execution-accuracy harness, schema validation, self-consistency voting, semantic layer
- [ ] Second contrastive-training round targeting the failure patterns from the full-eval manual review (missing joins, negation, schema confusion, stat-column misinterpretation, case sensitivity)
- [ ] RAG-based schema retrieval for large schemas; a large-schema test set
- [ ] Multi-dialect SQL support beyond Postgres

### Accounts and Security
- [x] API-key authentication (retained, currently unused by routes), password signup/login with JWT, Google OAuth, email verification, email normalization, rate limiting on account endpoints
- [x] Encrypted per-user connections with SSRF-safe validation; fail-fast startup validation
- [ ] SES email backend; KMS encryption backend
- [ ] Table allowlists and read-only role guidance; result row cap
- [ ] Per-account login throttling and timing equalization
- [ ] Static type checking; GitHub login

### Deployment Readiness
- [x] Live database connectivity, persistent model serving, request logging, rate limiting, GPU concurrency guard, CI
- [ ] Shared rate-limit store (DynamoDB or Redis); Alembic migrations
- [ ] Usage metering and billing
- [ ] Deployment infrastructure (hosting, uptime, scaling)

### Product Surface
- [ ] Frontend web interface; query history; account and usage page