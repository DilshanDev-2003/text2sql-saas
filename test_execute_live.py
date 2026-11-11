import time
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.db.result_limits import CappedRows
from app.db.runner import execute_live


def fake_engine():
  engine = MagicMock()
  connection = engine.connect.return_value.__enter__.return_value
  result = connection.execute.return_value
  return engine, connection, result


@pytest.mark.parametrize("truncated", [False, True])
def test_returns_rows_and_the_truncation_flag(truncated):
  engine, _, _ = fake_engine()

  with patch("app.db.runner.read_capped", return_value=CappedRows([(1,)], truncated)):
    out = execute_live(engine, "SELECT 1")

  assert out == {"ok": True, "rows": [(1,)], "truncated": truncated}


def test_streams_results_and_closes_the_cursor():
  engine, connection, result = fake_engine()

  with patch("app.db.runner.read_capped", return_value=CappedRows([], False)):
    execute_live(engine, "SELECT 1")

  assert connection.execute.call_args.kwargs["execution_options"] == {"stream_results": True}
  result.close.assert_called_once()


def test_cursor_is_closed_even_when_reading_fails():
  engine, _, result = fake_engine()

  with patch("app.db.runner.read_capped", side_effect=RuntimeError("boom")):
    out = execute_live(engine, "SELECT 1")

  assert out["ok"] is False
  assert out["error_type"] == "query_error"
  result.close.assert_called_once()


def test_non_select_statements_are_blocked_without_touching_the_database():
  engine, _, _ = fake_engine()

  out = execute_live(engine, "DROP TABLE singer")

  assert out["ok"] is False
  assert out["error_type"] == "blocked"
  engine.connect.assert_not_called()


def test_connection_failures_are_reported_as_unavailable():
  engine, _, _ = fake_engine()
  engine.connect.side_effect = OperationalError("SELECT 1", {}, Exception("down"))

  out = execute_live(engine, "SELECT 1")

  assert out["error_type"] == "db_unavailable"


def test_unexpected_errors_are_reported_as_query_errors():
  engine, connection, _ = fake_engine()
  connection.execute.side_effect = RuntimeError("boom")

  out = execute_live(engine, "SELECT 1")

  assert out["error_type"] == "query_error"


def test_timeout_returns_promptly():
  engine, connection, _ = fake_engine()
  connection.execute.side_effect = lambda *args, **kwargs: time.sleep(1)

  started = time.monotonic()
  out = execute_live(engine, "SELECT 1", timeout_seconds=0.1, connect_allowance_seconds=0)

  assert out["error_type"] == "timeout"
  assert time.monotonic() - started < 0.5

def test_slow_connection_gets_the_extra_allowance():
  engine, connection, _ = fake_engine()

  def slow_connect(*args, **kwargs):
    time.sleep(0.3)
    return MagicMock()

  connection.execute.side_effect = slow_connect

  with patch("app.db.runner.read_capped", return_value=CappedRows([(1,)], False)):
    out = execute_live(engine, "SELECT 1", timeout_seconds=0.1, connect_allowance_seconds=2)

  assert out["ok"] is True  