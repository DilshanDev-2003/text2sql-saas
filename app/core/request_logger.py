import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_LOG_PATH = "logs/request_log.jsonl"


def _log_path() -> Path:
  return Path(os.environ.get("REQUEST_LOG_PATH", DEFAULT_LOG_PATH))


def log_request(question, n, duration_seconds, status_code, sql=None, error=None):
  """Appends one JSON line per /generate request; never raises."""
  record = {
    "timestamp": time.time(),
    "question": question,
    "n": n,
    "duration_seconds": round(duration_seconds, 2),
    "status_code": status_code,
    "sql": sql,
    "error": error,
  }
  try:
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
      f.write(json.dumps(record) + "\n")
  except OSError:
    logger.warning("Could not write request log", exc_info=True)