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