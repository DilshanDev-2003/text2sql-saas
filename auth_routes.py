from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from auth import hash_password, verify_password, create_access_token, get_control_plane_engine

router = APIRouter()

class SignupRequest(BaseModel):
  email: EmailStr
  password: str

class LoginRequest(BaseModel):
  email: EmailStr
  password: str

class TokenResponse(BaseModel):
  access_token: str
  token_type: str = "bearer"

@router.post("/signup", response_model=TokenResponse)
def signup(req: SignupRequest):
  engine = get_control_plane_engine()
  password_hash = hash_password(req.password)

  with engine.begin() as conn:
    existing = conn.execute(
      text("SELECT id FROM users WHERE email = :email"),
      {"email": req.email},
    ).first()
    if existing:
      raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user_id = conn.execute(
      text("INSERT INTO users (email, password_hash) VALUES (:email, :password_hash) RETURNING id"),
      {"email": req.email, "password_hash": password_hash},
    ).scalar_one()

  token = create_access_token(user_id)
  return TokenResponse(access_token=token)

@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest):
  engine = get_control_plane_engine()

  with engine.connect() as conn:
    row = conn.execute(
      text("SELECT id, password_hash FROM users WHERE email = :email"),
      {"email": req.email},
    ).first()

  if row is None or not verify_password(req.password, row.password_hash):
    raise HTTPException(status_code=401, detail="Invalid email or password.")

  token = create_access_token(row.id)
  return TokenResponse(access_token=token)      