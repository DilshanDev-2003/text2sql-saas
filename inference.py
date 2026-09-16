from collections import Counter

import sqlglot
from sqlglot.expressions import Table, Column

from model_utils import generate_sql
from schema_validation import validate_sql
from db_runner import execute_queries, execute_live

def _eval_executor(db_path):
  """
    Adapts the SQLite eval path (execute_queries) to the same interface
    as execute_live: a callable taking sql and returning
    {"ok": bool, "rows"/"error": ...}.
  """
  def _run(sql):
    result = execute_queries(db_path, sql)
    if result is None:
      return {"ok": False, "error": "execution_failed"}
    return {"ok": True, "rows": result}
  return _run

def _live_executor(engine, timeout_seconds=5, readonly=True):
  """
     Same adapter shape as _eval_executor, wrapping execute_live so both
    paths present an identical interface to the generation strategies.
  """
  def _run(sql):
    return execute_live(engine, sql, timeout_seconds=timeout_seconds, readonly=readonly)
  return _run
         
def is_reasonable_query(sql, max_tables=8, dialect="sqlite"):
    try:
        parsed = sqlglot.parse_one(sql, read=dialect)
        n_tables = len(list(parsed.find_all(Table)))
        return n_tables <= max_tables
    except Exception:
        return False

def generate_sql_query_with_retry(model, tokenizer, question, db_id, schema_lookup, db_path=None, n=5, executor=None, live_schema=None, dialect="sqlite",):
  """
    executor: callable(sql) -> {"ok", "rows"/"error"}. If not provided,
    defaults to the SQLite eval path via db_path (existing behavior,
    unchanged for anything already calling this without executor).
    live_schema: when provided, validate_sql checks against it instead
    of schema_lookup[db_id] — matches the priority rule already built
    into validate_sql.
  """
  run = executor or _eval_executor(db_path)

  greedy = generate_sql(model, tokenizer, question, db_id, schema_lookup, live_schema=live_schema,do_sample=False)
  is_valid, problems = validate_sql(greedy, db_id, schema_lookup, dialect=dialect, live_schema=live_schema)
  if is_valid:
    result = run(greedy)
    if result["ok"]:
       return greedy 

  for _ in range(n):
    sql = generate_sql(model, tokenizer, question, db_id, schema_lookup, live_schema=live_schema,do_sample=True, temperature=0.7)
    is_valid, problems = validate_sql(sql, db_id, schema_lookup, dialect=dialect, live_schema=live_schema)
    if not is_valid:
      continue
    result = run(sql)
    if result["ok"]:
      return sql

  return greedy

def generate_candidates(model, tokenizer, question, db_id, schema_lookup, db_path, n=5, executor=None, live_schema=None, dialect="sqlite",):
    run = executor or _eval_executor(db_path)
    candidates = []
    failure_reasons = []
    
    for i in range(n):
        sql = generate_sql(model, tokenizer, question, db_id, schema_lookup, live_schema=live_schema,do_sample=True, temperature=0.7)
        if is_reasonable_query(sql, max_tables=8, dialect=dialect):
          is_valid, problems = validate_sql(sql, db_id, schema_lookup, dialect=dialect, live_schema=live_schema)
          if not is_valid:
            failure_reasons.append("invalid_sql")
            continue

          result = run(sql)
          if result["ok"]:
             candidates.append({"sql": sql, "result": result["rows"]})
          else:
             failure_reasons.append(result.get("error_type", "query_error"))
        else:
           failure_reasons.append("unreasonable_query")        

    return candidates, failure_reasons   

def voting_candidates(candidates):
  if not candidates:
    return None

  result_counts = Counter(tuple(sorted(c["result"])) for c in candidates)

  most_common_result, count = result_counts.most_common(1)[0]

  for c in candidates:
    if tuple(sorted(c["result"])) == most_common_result:
      return c

  return None    

def generate_sql_final(model, tokenizer, question, db_id, schema_lookup, db_path=None, n=5, executor=None, live_schema=None, dialect="sqlite"):
    """
      Returns {"sql": str, "result": list} on success, or {"sql": str,
      "result": None} on the greedy-fallback path (nothing validated
      and executed successfully, so there's no result to report).
    """
    candidates, failure_reasons = generate_candidates(model, tokenizer, question, db_id, schema_lookup, db_path, n=n, executor=executor, live_schema=live_schema, dialect=dialect)

    if not candidates:
        fallback_sql = generate_sql(model, tokenizer, question, db_id, schema_lookup, live_schema=live_schema,do_sample=False)
        # If every single attempt failed specifically because the DB was
        # unreachable, that's worth surfacing distinctly — not a generation
        # problem, an infrastructure one.
        db_unavailable = bool(failure_reasons) and all(r == "db_unavailable" for r in failure_reasons)
        return {
           "sql": fallback_sql,
           "result": None,
           "failure_reason": "db_unavailable" if db_unavailable else "generation_failed",
           }

    return voting_candidates(candidates)