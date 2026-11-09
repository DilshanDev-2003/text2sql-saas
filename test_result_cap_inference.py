from unittest.mock import patch

from app.services import inference


def run_candidates(executor):
  with patch("app.services.inference.generate_sql", return_value="SELECT 1"), \
       patch("app.services.inference.validate_sql", return_value=(True, [])), \
       patch("app.services.inference.is_reasonable_query", return_value=True):
    return inference.generate_candidates(
      None, None, "q", None, None, None,
      n=1, executor=executor, live_schema={"t": {}}, dialect="postgres",
    )


def test_candidates_carry_the_truncation_flag():
  candidates, _ = run_candidates(lambda sql: {"ok": True, "rows": [(1,)], "truncated": True})

  assert candidates[0]["truncated"] is True


def test_candidates_default_to_not_truncated_when_the_executor_omits_the_flag():
  candidates, _ = run_candidates(lambda sql: {"ok": True, "rows": [(1,)]})

  assert candidates[0]["truncated"] is False


def test_truncated_and_complete_results_never_vote_together():
  complete = {"sql": "SELECT a", "result": [(1,)], "truncated": False}
  first_truncated = {"sql": "SELECT b", "result": [(1,)], "truncated": True}
  second_truncated = {"sql": "SELECT c", "result": [(1,)], "truncated": True}

  winner = inference.voting_candidates([complete, first_truncated, second_truncated])

  assert winner["sql"] == "SELECT b"
  assert winner["truncated"] is True


def test_final_result_includes_the_truncation_flag():
  candidate = {"sql": "SELECT 1", "result": [(1,)], "truncated": True}
  with patch("app.services.inference.generate_candidates", return_value=([candidate], [])):
    final = inference.generate_sql_final(
      None, None, "q", None, None, n=1, live_schema={"t": {}}, dialect="postgres"
    )

  assert final["truncated"] is True