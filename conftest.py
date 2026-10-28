import os
import tempfile
import pytest

os.environ["JWT_SECRET"] = "test-jwt-secret-for-tests-only-0123456789"
os.environ["SESSION_SECRET"] = "test-session-secret-for-tests-only-0123456789"
os.environ["DATABASE_URL"] = ""
os.environ["CONTROL_PLANE_DATABASE_URL"] = ""
os.environ["REQUEST_LOG_PATH"] = os.path.join(tempfile.gettempdir(), "text2sql_test_request_log.jsonl")

os.environ["RATE_LIMIT_GENERATE"] = "10/minute"
os.environ["RATE_LIMIT_SIGNUP"] = "10/hour"
os.environ["RATE_LIMIT_LOGIN"] = "10/minute"
os.environ["RATE_LIMIT_RESEND"] = "5/hour"
os.environ["RATE_LIMIT_CONNECTIONS_CREATE"] = "10/hour"
os.environ["RATE_LIMIT_CONNECTIONS"] = "60/minute"

#Counters are shared across the whole test run. Now that /signup and /login are limited, any test file that calls them could inherit counts from earlier files. One autouse fixture covers every file. You can then delete the three per-file reset_limiter_storage fixtures (test_app.py, test_auth.py, test_verification.py), which are now duplicates.
@pytest.fixture(autouse=True)
def reset_rate_limits():
  from app.core.rate_limit import limiter

  limiter._storage.reset()
  yield
  limiter._storage.reset()