from collections import Counter

import sqlglot
from sqlglot.expressions import Table, Column

from model_utils import generate_sql
from schema_validation import validate_sql
from db_runner import execute_queries

def is_reasonable_query(sql, max_tables=8):
    try:
        parsed = sqlglot.parse_one(sql, read="sqlite")
        n_tables = len(list(parsed.find_all(Table)))
        return n_tables <= max_tables
    except Exception:
        return False

def generate_sql_query_with_retry(model, tokenizer, question, db_id, schema_lookup, db_path, n=5):
  greedy = generate_sql(model, tokenizer, question, db_id, schema_lookup, do_sample=False)
  is_valid, problems = validate_sql(greedy, db_id, schema_lookup)
  if is_valid:
    try:
      if execute_queries(db_path, greedy) is not None:
        return greedy
    except Exception:
      pass  

  for _ in range(n):
    sql = generate_sql(model, tokenizer, question, db_id, schema_lookup, do_sample=True, temperature=0.7)
    is_valid, problems = validate_sql(sql, db_id, schema_lookup)
    if not is_valid:
      continue
    try:
      if execute_queries(db_path, sql) is not None:
        return sql
    except Exception:
      continue

  return greedy

def generate_candidates(model, tokenizer, question, db_id, schema_lookup, db_path, n=5):
    candidates = []
    
    for i in range(n):
        sql = generate_sql(model, tokenizer, question, db_id, schema_lookup, do_sample=True, temperature=0.7)
        if is_reasonable_query(sql, max_tables=8):
          print(f"--- attempt {i} ---")
          print("SQL:", repr(sql))

          is_valid, problems = validate_sql(sql, db_id, schema_lookup)
          print("VALID:", is_valid, "PROBLEMS:", problems)

          if not is_valid:
            continue

          try:
            result = execute_queries(db_path, sql)
            print("RESULT:", result)
          except Exception as e:
            print("EXEC ERROR:", e)
            result = None

          if result is not None:
            candidates.append({"sql": sql, "result": result})

    return candidates    

def voting_candidates(candidates):
  if not candidates:
    return None

  result_counts = Counter(tuple(sorted(c["result"])) for c in candidates)

  most_common_result, count = result_counts.most_common(1)[0]

  for c in candidates:
    if tuple(sorted(c["result"])) == most_common_result:
      return c["sql"]

  return None    

def generate_sql_final(model, tokenizer, question, db_id, schema_lookup, db_path, n=5):
    candidates = generate_candidates(model, tokenizer, question, db_id, schema_lookup, db_path, n=n)

    if not candidates:
        # nothing valid/executable at all — fall back to a plain greedy attempt,
        # even if we already suspect it might fail, so we return SOMETHING
        return generate_sql(model, tokenizer, question, db_id, schema_lookup, do_sample=False)

    return voting_candidates(candidates)