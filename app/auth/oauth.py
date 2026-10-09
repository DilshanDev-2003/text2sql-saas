from authlib.integrations.starlette_client import OAuth

from app.core.config import get_google_client_id, get_google_client_secret

_oauth = None


def get_oauth() -> OAuth:
  global _oauth
  if _oauth is None:
    _oauth = OAuth()
    _oauth.register(
      name="google",
      client_id=get_google_client_id(),
      client_secret=get_google_client_secret(),
      server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
      client_kwargs={"scope": "openid email profile"},
    )
  return _oauth