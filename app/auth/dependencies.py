# The FastAPI dependency that checks a key on every request.
from fastapi import Header, HTTPException, Depends
from sqlalchemy import create_engine, text
from app.core.config import get_control_plane_connection_string
from app.auth.security import hash_api_key, decode_access_token

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

# The FastAPI dependency that protects a route with this token, mirroring
from fastapi import Header, HTTPException

async def require_user(authorization: str = Header(...)) -> int:
  if not authorization.startswith("Bearer "):
    raise HTTPException(status_code=401, detail="Missing or Invalid Authorization error")

  token = authorization.removeprefix("Bearer ")
  user_id = decode_access_token(token)

  if user_id is None:
    raise HTTPException(status_code=401, detail="Invalid or Expired Token")

  return user_id

def require_verified_user(user_id: int = Depends(require_user)) -> int:
  with get_control_plane_engine().connect() as conn:
    row = conn.execute(
      text("SELECT email_verified_at FROM users WHERE id = :id"),
      {"id": user_id},
    ).first()

  if row is None:
    raise HTTPException(status_code=401, detail="Invalid or expired token.")
  if row.email_verified_at is None:
    raise HTTPException(status_code=403, detail="Verify your email address before connecting a database.")
  return user_id