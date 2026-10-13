import os
from dotenv import load_dotenv

load_dotenv()

def get_connection_string(env_var: str = "DATABASE_URL") -> str:
  """
    Reads a database environment from an env file, instead of hardcoding.
  """
  value = os.environ.get(env_var)
  if not value:
    raise EnvironmentError(
      f"Missing required environment variable: {env_var}."
      f"Refer .env.example file."
    )
  return value

def get_hf_token(env_var: str = "HF_TOKEN") -> str | None:
  """
    Reads a Hugging Face token from an environment variable, if set.
    Unlike get_connection_string, a missing value here is not necessarily
    an error — a public model repo doesn't need one. Returns None rather
    than raising, so the caller decides whether that's a problem.
  """
  return os.environ.get(env_var)

def get_wandb_api_key(env_var: str = "WANDB_API_KEY") -> str | None:
  """
    Reads a Weights & Biases API key from an environment variable, if set.
    Like get_hf_token, a missing value isn't necessarily an error here —
    the caller decides whether wandb logging is required or optional.
  """
  return os.environ.get(env_var)

def get_rate_limit(env_var: str, default: str) -> str:
  return os.environ.get(env_var, default)

def get_max_concurrent_generations(env_var: str = "MAX_CONCURRENT_GENERATIONS", default: int = 1) -> int:
  return int(os.environ.get(env_var, default))

def get_control_plane_connection_string() -> str:
  return get_connection_string("CONTROL_PLANE_DATABASE_URL")

def get_jwt_secret() -> str:
  return get_connection_string("JWT_SECRET")

#OAuth
def get_required_env(env_var: str) -> str:
  value = os.environ.get(env_var)
  if not value:
    raise EnvironmentError(f"Missing required environment variable: {env_var}.")
  return value


def get_google_client_id() -> str:
  return get_required_env("GOOGLE_CLIENT_ID")


def get_google_client_secret() -> str:
  return get_required_env("GOOGLE_CLIENT_SECRET")


def get_session_secret() -> str:
  return get_required_env("SESSION_SECRET")

def get_google_redirect_uri() -> str:
  return os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")

# E-mail Verification
def get_email_backend() -> str:
  return os.environ.get("EMAIL_BACKEND", "console")

def get_frontend_url() -> str:
  return os.environ.get("FRONTEND_URL", "http://localhost:3000")