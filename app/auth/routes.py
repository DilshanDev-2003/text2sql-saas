from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import text

from app.auth.dependencies import get_control_plane_engine
from app.auth.security import hash_password, verify_password, create_access_token
from app.auth.verification import (
  create_verification_token,
  send_verification_email,
  verify_email_token,
  resend_verification,
)
from app.core.rate_limit import limiter, RESEND_LIMIT

router = APIRouter()


class SignupRequest(BaseModel):
  email: EmailStr
  password: str


class LoginRequest(BaseModel):
  email: EmailStr
  password: str


class VerifyEmailRequest(BaseModel):
  token: str


class ResendRequest(BaseModel):
  email: EmailStr


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
    verification_token = create_verification_token(conn, user_id)

  send_verification_email(req.email, verification_token)
  return TokenResponse(access_token=create_access_token(user_id))


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest):
  engine = get_control_plane_engine()

  with engine.connect() as conn:
    row = conn.execute(
      text("SELECT id, password_hash FROM users WHERE email = :email"),
      {"email": req.email},
    ).first()

  if row is None or row.password_hash is None or not verify_password(req.password, row.password_hash):
    raise HTTPException(status_code=401, detail="Invalid email or password.")

  return TokenResponse(access_token=create_access_token(row.id))


@router.post("/auth/verify-email")
def verify_email(req: VerifyEmailRequest):
  if not verify_email_token(get_control_plane_engine(), req.token):
    raise HTTPException(status_code=400, detail="Invalid or expired verification token.")
  return {"status": "verified"}


@router.post("/auth/resend-verification")
@limiter.limit(RESEND_LIMIT)
def resend(request: Request, response: Response, req: ResendRequest):
  resend_verification(get_control_plane_engine(), req.email)
  return {"status": "ok"}