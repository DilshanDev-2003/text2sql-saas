import json

from app.core.request_logger import log_request


def test_writes_one_json_line_per_request(tmp_path, monkeypatch):
  path = tmp_path / "request_log.jsonl"
  monkeypatch.setenv("REQUEST_LOG_PATH", str(path))

  log_request("average age", 5, 1.234, 200, sql="SELECT 1")
  log_request("bad", 5, 0.5, 422, sql="SELECT x", error="generation_failed")

  lines = path.read_text().splitlines()
  assert len(lines) == 2
  first = json.loads(lines[0])
  assert first["question"] == "average age"
  assert first["duration_seconds"] == 1.23
  assert first["status_code"] == 200
  assert json.loads(lines[1])["error"] == "generation_failed"


def test_creates_missing_parent_directories(tmp_path, monkeypatch):
  path = tmp_path / "nested" / "dir" / "log.jsonl"
  monkeypatch.setenv("REQUEST_LOG_PATH", str(path))

  log_request("q", 1, 0.1, 200)

  assert path.exists()


def test_write_failure_does_not_raise(tmp_path, monkeypatch):
  blocker = tmp_path / "not_a_directory"
  blocker.write_text("x")
  monkeypatch.setenv("REQUEST_LOG_PATH", str(blocker / "log.jsonl"))

  log_request("q", 1, 0.1, 200)