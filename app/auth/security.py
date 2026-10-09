# API Key
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

# Password
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
  return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
  return pwd_context.verify(password, password_hash)

# ------ JWT ------
import jwt
from datetime import datetime, timedelta, timezone
from app.core.config import get_jwt_secret

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_MINUTES = 60

def create_access_token(user_id: int) -> str:
  payload = {
    "sub": str(user_id),
    "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRY_MINUTES),
  }
  return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)

def decode_access_token(token: str) -> int | None:
  try:
    payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    return int(payload["sub"])
  except jwt.PyJWTError:
    return None