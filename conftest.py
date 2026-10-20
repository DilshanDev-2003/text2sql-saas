import os
import tempfile

os.environ["JWT_SECRET"] = "test-jwt-secret-for-tests-only-0123456789"
os.environ["SESSION_SECRET"] = "test-session-secret-for-tests-only-0123456789"
os.environ["DATABASE_URL"] = ""
os.environ["CONTROL_PLANE_DATABASE_URL"] = ""
os.environ["REQUEST_LOG_PATH"] = os.path.join(tempfile.gettempdir(), "text2sql_test_request_log.jsonl")