from sqlalchemy import text

from app.auth.dependencies import get_control_plane_engine


class EmailAlreadyRegistered(Exception):
  pass


def find_or_create_oauth_user(provider: str, provider_user_id: str, email: str) -> int:
  engine = get_control_plane_engine()

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
      text("SELECT id FROM users WHERE email = :email"),
      {"email": email},
    ).first()
    if existing:
      raise EmailAlreadyRegistered()

    user_id = conn.execute(
      text("INSERT INTO users (email) VALUES (:email) RETURNING id"),
      {"email": email},
    ).scalar_one()

    conn.execute(
      text(
        "INSERT INTO oauth_identities (user_id, provider, provider_user_id) "
        "VALUES (:user_id, :provider, :provider_user_id)"
      ),
      {"user_id": user_id, "provider": provider, "provider_user_id": provider_user_id},
    )
    return user_id