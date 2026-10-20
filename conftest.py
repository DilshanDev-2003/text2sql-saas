import os
import tempfile

os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ["EMAIL_BACKEND"] = "console"
os.environ["REQUEST_LOG_PATH"] = os.path.join(tempfile.gettempdir(), "text2sql_test_request_log.jsonl")