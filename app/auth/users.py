from datetime import datetime, timezone

from sqlalchemy import text

from app.auth.dependencies import get_control_plane_engine


def _link_identity(conn, user_id: int, provider: str, provider_user_id: str) -> None:
  conn.execute(
    text(
      "INSERT INTO oauth_identities (user_id, provider, provider_user_id) "
      "VALUES (:user_id, :provider, :provider_user_id)"
    ),
    {"user_id": user_id, "provider": provider, "provider_user_id": provider_user_id},
  )


def find_or_create_oauth_user(provider: str, provider_user_id: str, email: str) -> int:
  engine = get_control_plane_engine()
  now = datetime.now(timezone.utc)

  with engine.begin() as conn:
    identity = conn.execute(
      text(
        "SELECT user_id FROM oauth_identities "
        "WHERE provider = :provider AND provider_user_id = :provider_user_id"
      ),
      {"provider": provider, "provider_user_id": provider_user_id},
    ).first()
    if identity:
      return identity[0]

    existing = conn.execute(
      text("SELECT id, email_verified_at FROM users WHERE email = :email FOR UPDATE"),
      {"email": email},
    ).first()

    if existing and existing.email_verified_at is not None:
      _link_identity(conn, existing.id, provider, provider_user_id)
      return existing.id

    if existing:
      conn.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": existing.id})

    user_id = conn.execute(
      text("INSERT INTO users (email, email_verified_at) VALUES (:email, :now) RETURNING id"),
      {"email": email, "now": now},
    ).scalar_one()
    _link_identity(conn, user_id, provider, provider_user_id)
    return user_id