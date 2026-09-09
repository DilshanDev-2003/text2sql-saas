import pytest
import inference


# --- voting_candidates ---

def test_voting_candidates_returns_full_dict_not_just_sql():
  candidates = [
    {"sql": "SELECT a FROM t", "result": [(1,), (2,)]},
    {"sql": "SELECT a FROM t", "result": [(1,), (2,)]},
    {"sql": "SELECT DISTINCT a FROM t", "result": [(3,)]},
  ]
  winner = inference.voting_candidates(candidates)
  assert winner == {"sql": "SELECT a FROM t", "result": [(1,), (2,)]}

def test_voting_candidates_empty_list_returns_none():
  assert inference.voting_candidates([]) is None

def test_voting_candidates_single_candidate():
  candidates = [{"sql": "SELECT 1", "result": [(1,)]}]
  assert inference.voting_candidates(candidates) == candidates[0]


# --- generate_sql_final return shape ---

def test_generate_sql_final_returns_dict_with_result_on_success(monkeypatch):
  # stub generate_sql: always returns the same SQL string regardless of args
  monkeypatch.setattr(inference, "generate_sql", lambda *a, **k: "SELECT name FROM singer")
  # stub validate_sql: always valid
  monkeypatch.setattr(inference, "validate_sql", lambda *a, **k: (True, []))

  fake_executor = lambda sql: {"ok": True, "rows": [("Alice",), ("Bob",)]}

  output = inference.generate_sql_final(
    model=None, tokenizer=None, question="who are the singers?",
    db_id=None, schema_lookup=None, executor=fake_executor,
    live_schema={"singer": {"columns": [], "primary_key": [], "foreign_keys": []}},
    dialect="postgres", n=3,
  )

  assert output["sql"] == "SELECT name FROM singer"
  assert output["result"] == [("Alice",), ("Bob",)]

def test_generate_sql_final_falls_back_when_nothing_executes(monkeypatch):
  # every candidate fails validation, so generate_candidates returns []
  monkeypatch.setattr(inference, "generate_sql", lambda *a, **k: "SELECT bad FROM nowhere")
  monkeypatch.setattr(inference, "validate_sql", lambda *a, **k: (False, ["Unknown table"]))

  fake_executor = lambda sql: {"ok": False, "error": "should not be called"}

  output = inference.generate_sql_final(
    model=None, tokenizer=None, question="...", db_id=None, schema_lookup=None,
    executor=fake_executor, live_schema={}, dialect="postgres", n=3,
  )

  assert output["sql"] == "SELECT bad FROM nowhere"
  assert output["result"] is None

def test_generate_sql_final_result_matches_majority_not_first_candidate(monkeypatch):
  # 3 candidates generated; 2 agree on one result, 1 disagrees — voting
  # should pick the majority result even though it's not the first generated
  calls = iter(["SELECT a", "SELECT b", "SELECT a"])
  monkeypatch.setattr(inference, "generate_sql", lambda *a, **k: next(calls))
  monkeypatch.setattr(inference, "validate_sql", lambda *a, **k: (True, []))

  results_by_sql = {
    "SELECT a": [("majority",)],
    "SELECT b": [("minority",)],
  }
  fake_executor = lambda sql: {"ok": True, "rows": results_by_sql[sql]}

  output = inference.generate_sql_final(
    model=None, tokenizer=None, question="...", db_id=None, schema_lookup=None,
    executor=fake_executor, live_schema={}, dialect="postgres", n=3,
  )

  assert output["result"] == [("majority",)]


# --- executor swapping: live vs eval ---

def test_live_executor_wraps_execute_live(monkeypatch):
  captured = {}

  def fake_execute_live(engine, sql, timeout_seconds=5, readonly=True):
    captured["args"] = (engine, sql, timeout_seconds, readonly)
    return {"ok": True, "rows": [(1,)]}

  monkeypatch.setattr(inference, "execute_live", fake_execute_live)

  run = inference._live_executor(engine="fake_engine", timeout_seconds=10, readonly=True)
  result = run("SELECT 1")

  assert result == {"ok": True, "rows": [(1,)]}
  assert captured["args"] == ("fake_engine", "SELECT 1", 10, True)

def test_eval_executor_wraps_execute_queries_none_as_failure(monkeypatch):
  # execute_queries returning None (its existing "query failed" signal)
  # should surface as {"ok": False}, not crash
  monkeypatch.setattr(inference, "execute_queries", lambda db_path, sql: None)

  run = inference._eval_executor(db_path="fake.db")
  result = run("SELECT bad")

  assert result == {"ok": False, "error": "execution_failed"}

def test_eval_executor_wraps_execute_queries_success(monkeypatch):
  monkeypatch.setattr(inference, "execute_queries", lambda db_path, sql: [(1,), (2,)])

  run = inference._eval_executor(db_path="fake.db")
  result = run("SELECT ok")

  assert result == {"ok": True, "rows": [(1,), (2,)]}