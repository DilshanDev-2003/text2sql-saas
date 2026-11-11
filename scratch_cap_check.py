import os
import time

from app.core import config  # noqa: F401
from app.db.connection import build_customer_engine
from app.db.connection_safety import validate_connection_string
from app.db.runner import execute_live

target = validate_connection_string(os.environ["TEST_CUSTOMER_DB_URL"])
engine = build_customer_engine(target)

"""
def timed(label, sql, **kwargs):
  started = time.time()
  out = execute_live(engine, sql, timeout_seconds=30, **kwargs)
  print(label, "| ok:", out["ok"], "| type:", out.get("error_type"),
        "| rows:", len(out.get("rows", [])), "| truncated:", out.get("truncated"),
        "|", round(time.time() - started, 2), "s")
  if not out["ok"]:
    print("   ", out["error"][:300])


timed("warm-up 1", "SELECT 1")
timed("warm-up 2", "SELECT 1")
timed("big query", "SELECT g, md5(g::text) FROM generate_series(1, 5000000) g")
timed("singer rows", "SELECT count(*) FROM singer")
timed("delete (guard off)", "DELETE FROM singer", readonly=False)
timed("singer rows after", "SELECT count(*) FROM singer")
"""
from sqlalchemy import text


def plain(label, sql):
  started = time.time()
  with engine.connect() as c:
    value = c.execute(text(sql)).fetchall()
  print(label, value, round(time.time() - started, 2), "s")


plain("plain SELECT 1", "SELECT 1")
plain("plain SELECT 1 again", "SELECT 1")
plain("singer count", "SELECT count(*) FROM singer")

with engine.connect() as c:
  try:
    c.execute(text("DELETE FROM singer"))
    print("DELETE executed inside a transaction that is rolled back at exit")
  except Exception as e:
    print("Database refused:", type(e).__name__, str(e).splitlines()[0])

plain("singer count after", "SELECT count(*) FROM singer")