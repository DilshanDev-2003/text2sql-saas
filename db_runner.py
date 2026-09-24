import sqlite3
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from query_guard import guard_readonly
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

def execute_queries(db_path, query, timeout_seconds=5):
  conn = sqlite3.connect(db_path, timeout=timeout_seconds)
  conn.execute(f"PRAGMA busy_timeout = {timeout_seconds * 1000}")
  cursor = conn.cursor()
  try:
    cursor.execute(query)
    results = cursor.fetchall()
  except Exception as e:
    results = None
  conn.close()
  return results

def execute_live(engine, query, timeout_seconds=5, readonly=True):
  """
    Executes SQL against a live SQLAlchemy-connected database (Postgres,
    MySQL, etc.)
  """
  if readonly:
    guard_readonly(query)

  def _run():
    with engine.connect() as connection:
      results = connection.execute(text(query))
      return [tuple(row) for row in results.fetchall()]

  with ThreadPoolExecutor(max_workers=1) as executor:
    future = executor.submit(_run)
    try:
      return {"ok": True, "rows": future.result(timeout=timeout_seconds)}
    except FutureTimeoutError:
      return {"ok": False, "error_type": "timeout", "error": "query_timeout"}
    except OperationalError as e:
      return {"ok": False, "error_type": "db_unavailable", "error": str(e)}
    except Exception as e:
      return {"ok": False, "error_type": "query_error", "error": str(e)}

def compare_execution(db_path, ac_sql, gen_sql):
  ac_res = execute_queries(db_path, ac_sql)
  gen_res = execute_queries(db_path, gen_sql)

  if gen_res is None or ac_res is None:
    return False

  def normalize(rows):
    """
      Sorts values *within* each row (so column order doesn't matter)
      and then sorts the rows themselves (so row order doesn't matter
      either). Values are stringified first, same reasoning as the
      earlier sorting fix — keeps mixed types (e.g. None next to an
      int) comparable.
    """
    row_signatures = [tuple(sorted(str(v) for v in row)) for row in rows]
    return sorted(row_signatures)

  return normalize(ac_res) == normalize(gen_res)