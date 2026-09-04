# Text2SQL SaaS

A text-to-SQL system: given a natural language question and a database schema, generates correct SQL. Built around a fine-tuned Llama 3.2 3B model, with a schema-validation and self-consistency layer to catch and correct common failure modes before returning an answer.

## Status

Actively in development. Core generation pipeline (fine-tuned model + schema validation + majority-vote consistency checking) is built and tested. Broader production concerns (multi-tenant security, RAG-based schema retrieval, semantic layer, multi-dialect SQL) are deliberately not yet built — see [Roadmap](#roadmap).

## How it works

1. A question + database schema go into the fine-tuned model. If the question uses a known business term (e.g., domain-specific jargon not present in the schema), its real SQL meaning is injected into the prompt first (`semantic_layer.py`).
2. The model generates candidate SQL.
3. Each candidate is checked against the real schema (`schema_validation.py`) — catches hallucinated column/table names before ever touching a database.
4. Surviving candidates are executed against the database (`db_runner.py`), with a timeout guard against runaway queries.
5. If multiple candidates were generated, the most self-consistent answer wins — the SQL whose *result* the most candidates agree on, not just the first one that happened to run (`inference.py`).

## Project structure

| File | Responsibility |
|---|---|
| `schema_validation.py` | Checks if generated SQL only references real tables/columns. No model or database needed. |
| `db_runner.py` | Executes SQL against a SQLite file safely, with a timeout; compares two queries' results. |
| `model_utils.py` | Talks to the fine-tuned model — prompt formatting and generation only. |
| `semantic_layer.py` | Maps business terminology to real SQL logic, so questions using jargon the schema doesn't cover still resolve correctly. |
| `inference.py` | Combines the above into full generation strategies (first-valid-wins retry, and generate-many-then-vote). |

Model training and full evaluation runs live in a separate Colab notebook (GPU required); the modules above are local, GPU-free application code.

## Setup

Local development (schema validation, execution, tests — no GPU needed):

```bash
pip install -r requirements.txt
```

Training/inference (Colab, GPU required):

```bash
pip install -r requirements-training.txt
```

## Running tests

```bash
pytest -v
```

Covers `schema_validation.py`, `db_runner.py`, and `inference.py`'s logic (with the model generation step mocked out, so no GPU is needed to run the test suite).

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

- [x] Fine-tuned base model
- [x] Execution-accuracy evaluation harness
- [x] Schema validation (pre-execution hallucination guard)
- [x] Self-consistency (majority-vote) generation
- [x] Semantic layer (business terminology → SQL mapping)
- [ ] RAG-based schema retrieval (for schemas too large to fit in one prompt)
- [ ] Multi-dialect SQL support (Postgres, Snowflake, BigQuery)
- [ ] Production hardening (multi-tenant security, auth, deployment infrastructure)