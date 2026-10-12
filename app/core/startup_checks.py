import os

from huggingface_hub import get_token
from sqlalchemy import inspect

REQUIRED_ENV_VARS = [
  "DATABASE_URL",
  "CONTROL_PLANE_DATABASE_URL",
  "JWT_SECRET",
  "SESSION_SECRET",
]

CONTROL_PLANE_TABLES = {"tenants", "api_keys", "users"}
CONTROL_PLANE_FINGERPRINT = {"api_keys", "oauth_identities"}


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


def check_schema(live_schema: dict) -> list[str]:
  if not live_schema:
    return ["The generation database has no tables in the 'public' schema."]
  if CONTROL_PLANE_FINGERPRINT <= set(live_schema):
    return ["The generation database contains the control-plane tables; point DATABASE_URL at customer data."]
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