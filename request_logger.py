import json
import time
from pathlib import Path

LOG_PATH = "/content/drive/MyDrive/text2sql-eval/request_log.jsonl"

def log_request(question, n, duration_seconds, status_code, sql=None, error=None):
  """
    One json line per /generate request. Rather than print in a Colab, this writes the logs in a Google Drive.
    After we can use them to create rate limitings, or any failure types.
  """
  record = {
    "timestamp": time.time(),
    "question": question,
    "n": n,
    "duration_seconds": duration_seconds,
    "status_code": status_code,
    "sql": sql,
    "error": error,
  }
  Path(LOG_PATH).parent.mkdir(parent=True, exist_ok=True)
  with open(LOG_PATH, "a") as f:
    f.write(json.dumps(record) + "\n")