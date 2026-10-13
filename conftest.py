import os

os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ["EMAIL_BACKEND"] = "console"