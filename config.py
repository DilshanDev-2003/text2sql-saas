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