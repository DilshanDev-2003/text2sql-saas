import os
import time

from app.core import config  # noqa: F401
from app.db.connection import build_customer_engine
from app.db.connection_safety import validate_connection_string
from app.db.runner import execute_live

target = validate_connection_string(os.environ["TEST_CUSTOMER_DB_URL"])
engine = build_customer_engine(target)

started = time.time()
out = execute_live(engine, "SELECT g, md5(g::text) FROM generate_series(1, 5000000) g")
print(out["ok"], len(out.get("rows", [])), out.get("truncated"), round(time.time() - started, 2), "s")

print(execute_live(engine, "DELETE FROM singer"))
print(execute_live(engine, "DELETE FROM singer", readonly=False)["error_type"])