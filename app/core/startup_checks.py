import os

from huggingface_hub import get_token
from sqlalchemy import inspect

from app.core.encryption import get_encryptor

REQUIRED_ENV_VARS = [
  "CONTROL_PLANE_DATABASE_URL",
  "JWT_SECRET",
  "SESSION_SECRET",
  "ENCRYPTION_KEYS",
  "ENCRYPTION_KEY_VERSION",
]

CONTROL_PLANE_TABLES = {
  "tenants",
  "api_keys",
  "users",
  "oauth_identities",
  "email_verifications",
  "db_connections",
}


class StartupError(RuntimeError):
  pass


def check_environment() -> list[str]:
  problems = [
    f"Missing environment variable: {name}"
    for name in REQUIRED_ENV_VARS
    if not os.environ.get(name)
  ]
  if not get_token():
    problems.append("No Hugging Face token found (set HF_TOKEN or log in); the base model is gated.")
  return problems


def check_encryption() -> list[str]:
  try:
    encryptor = get_encryptor()
    probe = encryptor.encrypt("startup-check", "startup")
    if encryptor.decrypt(probe.ciphertext, probe.key_version, "startup") != "startup-check":
      raise ValueError("round trip mismatch")
  except Exception as e:
    return [
      f"Encryption is misconfigured ({type(e).__name__}). Check ENCRYPTION_BACKEND, "
      "ENCRYPTION_KEYS (format 1:<base64 32-byte key>), and ENCRYPTION_KEY_VERSION."
    ]
  return []


def check_control_plane(engine) -> list[str]:
  try:
    tables = set(inspect(engine).get_table_names())
  except Exception as e:
    return [f"Cannot reach the control-plane database: {str(e).splitlines()[0]}"]
  missing = CONTROL_PLANE_TABLES - tables
  if missing:
    return [f"Control-plane database is missing tables: {', '.join(sorted(missing))}"]
  return []


def raise_if_problems(problems: list[str]) -> None:
  if problems:
    raise StartupError("Startup checks failed:\n- " + "\n- ".join(problems))