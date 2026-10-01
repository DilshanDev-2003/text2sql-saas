import hashlib
import hmac
import secrets

KEY_PREFIX = "t2s_live_"

def generate_api_key() -> str:
  secret = secrets.token_urlsafe(32)
  return f"{KEY_PREFIX}{secret}"

def hash_api_key(key: str) -> str:
  return hashlib.sha256(key.encode()).hexdigest()

def verify_api_key(key: str, stored_hash: str) -> bool:
  return hmac.compare_digest(hash_api_key(key), stored_hash)

# The FastAPI dependency that checks a key on every request.
from fastapi import Header, HTTPException
from sqlalchemy import create_engine, text
from config import get_control_plane_connection_string

_control_plane_engine = None

def get_control_plane_engine():
  global _control_plane_engine
  if _control_plane_engine is None:
    _control_plane_engine = create_engine(get_control_plane_connection_string())
  return _control_plane_engine

def lookup_tenant(key: str) -> int | None:
  key_hash = hash_api_key(key)
  engine = get_control_plane_engine()

  with engine.connect() as conn:
    row = conn.execute(
      text("SELECT tenant_id FROM api_keys "
           "WHERE key_hash = :key_hash AND revoked_at IS NULL"
      ),
      {"key_hash": key_hash}
    ).first()

  return row[0] if row else None

def require_api_key(x_api_key: str = Header(...)) -> int:
  tenant_id = lookup_tenant(x_api_key)
  if tenant_id is None:
    raise HTTPException(status_code=401, detail="Invalid or missing API Key")     
  return tenant_id