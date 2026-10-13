import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.auth.security import generate_email_token, hash_token
from app.core.config import get_frontend_url
from app.core.email_sender import get_email_sender

logger = logging.getLogger(__name__)

VERIFICATION_TTL_HOURS = 24


def create_verification_token(conn, user_id: int) -> str:
  token = generate_email_token()
  conn.execute(
    text("DELETE FROM email_verifications WHERE user_id = :user_id"),
    {"user_id": user_id},
  )
  conn.execute(
    text(
      "INSERT INTO email_verifications (user_id, token_hash, expires_at) "
      "VALUES (:user_id, :token_hash, :expires_at)"
    ),
    {
      "user_id": user_id,
      "token_hash": hash_token(token),
      "expires_at": datetime.now(timezone.utc) + timedelta(hours=VERIFICATION_TTL_HOURS),
    },
  )
  return token


def send_verification_email(email: str, token: str) -> None:
  link = f"{get_frontend_url()}/verify-email?token={token}"
  body = (
    f"Confirm your email address by opening this link:\n\n{link}\n\n"
    f"The link expires in {VERIFICATION_TTL_HOURS} hours. "
    "If you didn't create an account, you can ignore this email."
  )
  try:
    get_email_sender().send(email, "Confirm your email", body)
  except Exception:
    logger.exception("Failed to send verification email")


def verify_email_token(engine, token: str) -> bool:
  now = datetime.now(timezone.utc)
  with engine.begin() as conn:
    row = conn.execute(
      text(
        "SELECT user_id FROM email_verifications "
        "WHERE token_hash = :token_hash AND expires_at > :now"
      ),
      {"token_hash": hash_token(token), "now": now},
    ).first()
    if row is None:
      return False

    user_id = row[0]
    conn.execute(
      text("UPDATE users SET email_verified_at = COALESCE(email_verified_at, :now) WHERE id = :user_id"),
      {"now": now, "user_id": user_id},
    )
    conn.execute(
      text("DELETE FROM email_verifications WHERE user_id = :user_id"),
      {"user_id": user_id},
    )
  return True


def resend_verification(engine, email: str) -> None:
  with engine.begin() as conn:
    row = conn.execute(
      text("SELECT id FROM users WHERE email = :email AND email_verified_at IS NULL"),
      {"email": email},
    ).first()
    if row is None:
      return
    token = create_verification_token(conn, row[0])

  send_verification_email(email, token)