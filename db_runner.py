import sqlite3

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

def compare_execution(db_path, ac_sql, gen_sql):
  ac_res = execute_queries(db_path, ac_sql)
  gen_res = execute_queries(db_path, gen_sql)

  if gen_res is None or ac_res is None:
    return False

  return set(gen_res) == set(ac_res)