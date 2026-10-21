import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.encryption import DecryptionError
from app.db.connection import build_customer_engine, get_live_schema
from app.db.connection_safety import validate_connection_string
from app.services.connection_cache import CachedConnection

logger = logging.getLogger(__name__)

MAX_CONNECTIONS_PER_USER = 5
MAX_NAME_LENGTH = 100

CONNECT_FAILED_MESSAGE = (
  "Could not connect with these credentials. Check the host, user, password, and database. "
  "If the connection string uses a connection pooler, use the direct connection instead."
)
NO_TABLES_MESSAGE = (
  "Connected, but no tables are visible in the public schema. "
  "Check that this user can read your tables."
)
NAME_TAKEN_MESSAGE = "You already have a connection with this name."
NOT_FOUND_MESSAGE = "Connection not found."
UNREADABLE_MESSAGE = "This saved connection can no longer be read. Please delete it and add it again."


class ConnectionServiceError(Exception):
  pass


class InvalidConnectionName(ConnectionServiceError):
  pass


class ConnectionLimitReached(ConnectionServiceError):
  pass


class ConnectionNameTaken(ConnectionServiceError):
  pass


class ConnectionNotFound(ConnectionServiceError):
  pass


class ConnectionTestFailed(ConnectionServiceError):
  pass


class ConnectionUnreadable(ConnectionServiceError):
  pass


def _context(user_id: int) -> str:
  return f"user:{user_id}"


def _clean_name(name: str) -> str:
  cleaned = name.strip()
  if not cleaned or len(cleaned) > MAX_NAME_LENGTH:
    raise InvalidConnectionName(f"Connection names must be 1 to {MAX_NAME_LENGTH} characters.")
  return cleaned


def _introspect(engine) -> dict:
  try:
    schema = get_live_schema(engine)
  except SQLAlchemyError as e:
    logger.info("Connection test failed: %s", type(e).__name__)
    raise ConnectionTestFailed(CONNECT_FAILED_MESSAGE) from None
  if not schema:
    raise ConnectionTestFailed(NO_TABLES_MESSAGE)
  return schema


def _insert(cp_engine, user_id, name, target, encrypted):
  try:
    with cp_engine.begin() as conn:
      return conn.execute(
        text(
          "INSERT INTO db_connections "
          "(user_id, name, host, database_name, encrypted_connection_string, key_version, last_connected_at) "
          "VALUES (:user_id, :name, :host, :database_name, :ciphertext, :key_version, :now) "
          "RETURNING id, created_at"
        ),
        {
          "user_id": user_id,
          "name": name,
          "host": target.host,
          "database_name": target.database,
          "ciphertext": encrypted.ciphertext,
          "key_version": encrypted.key_version,
          "now": datetime.now(timezone.utc),
        },
      ).one()
  except IntegrityError:
    raise ConnectionNameTaken(NAME_TAKEN_MESSAGE) from None


def _touch(cp_engine, connection_id: int) -> None:
  try:
    with cp_engine.begin() as conn:
      conn.execute(
        text("UPDATE db_connections SET last_connected_at = :now WHERE id = :id"),
        {"now": datetime.now(timezone.utc), "id": connection_id},
      )
  except SQLAlchemyError:
    logger.warning("Could not update last_connected_at", exc_info=True)


def create_connection(cp_engine, user_id, name, connection_string, encryptor, cache) -> dict:
  name = _clean_name(name)

  with cp_engine.connect() as conn:
    usage = conn.execute(
      text(
        "SELECT count(*) AS total, count(*) FILTER (WHERE name = :name) AS same_name "
        "FROM db_connections WHERE user_id = :user_id"
      ),
      {"user_id": user_id, "name": name},
    ).one()
  if usage.total >= MAX_CONNECTIONS_PER_USER:
    raise ConnectionLimitReached(
      f"You can save up to {MAX_CONNECTIONS_PER_USER} connections. Delete one to add another."
    )
  if usage.same_name:
    raise ConnectionNameTaken(NAME_TAKEN_MESSAGE)

  target = validate_connection_string(connection_string)
  engine = build_customer_engine(target)
  try:
    schema = _introspect(engine)
    encrypted = encryptor.encrypt(
      target.url.render_as_string(hide_password=False), _context(user_id)
    )
    row = _insert(cp_engine, user_id, name, target, encrypted)
  except Exception:
    engine.dispose()
    raise

  cache.put(row.id, engine, schema)
  return {
    "id": row.id,
    "name": name,
    "host": target.host,
    "database_name": target.database,
    "created_at": row.created_at,
  }


def list_connections(cp_engine, user_id) -> list[dict]:
  with cp_engine.connect() as conn:
    rows = conn.execute(
      text(
        "SELECT id, name, host, database_name, created_at, last_connected_at "
        "FROM db_connections WHERE user_id = :user_id ORDER BY created_at, id"
      ),
      {"user_id": user_id},
    ).all()

  return [
    {
      "id": r.id,
      "name": r.name,
      "host": r.host,
      "database_name": r.database_name,
      "created_at": r.created_at,
      "last_connected_at": r.last_connected_at,
    }
    for r in rows
  ]


def delete_connection(cp_engine, cache, user_id, connection_id) -> None:
  with cp_engine.begin() as conn:
    deleted = conn.execute(
      text("DELETE FROM db_connections WHERE id = :id AND user_id = :user_id RETURNING id"),
      {"id": connection_id, "user_id": user_id},
    ).first()
  if deleted is None:
    raise ConnectionNotFound(NOT_FOUND_MESSAGE)
  cache.evict(connection_id)


def get_connection_entry(cp_engine, cache, encryptor, user_id, connection_id) -> CachedConnection:
  with cp_engine.connect() as conn:
    row = conn.execute(
      text(
        "SELECT encrypted_connection_string, key_version FROM db_connections "
        "WHERE id = :id AND user_id = :user_id"
      ),
      {"id": connection_id, "user_id": user_id},
    ).first()
  if row is None:
    raise ConnectionNotFound(NOT_FOUND_MESSAGE)

  cached = cache.get(connection_id)
  if cached is not None:
    return cached

  try:
    plaintext = encryptor.decrypt(
      row.encrypted_connection_string, row.key_version, _context(user_id)
    )
  except DecryptionError:
    logger.error("Stored connection %s could not be decrypted", connection_id)
    raise ConnectionUnreadable(UNREADABLE_MESSAGE) from None

  target = validate_connection_string(plaintext)
  engine = build_customer_engine(target)
  try:
    schema = _introspect(engine)
  except Exception:
    engine.dispose()
    raise

  entry = cache.put(connection_id, engine, schema)
  _touch(cp_engine, connection_id)
  return entry