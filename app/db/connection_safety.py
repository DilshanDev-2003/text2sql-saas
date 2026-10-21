import ipaddress
import socket
from dataclasses import dataclass

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

ALLOWED_DRIVERS = {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
ALLOWED_QUERY_PARAMS = {"sslmode", "channel_binding"}
SECURE_SSL_MODES = {"require", "verify-ca", "verify-full"}
CHANNEL_BINDING_MODES = {"disable", "prefer", "require"}
MAX_CONNECTION_STRING_LENGTH = 2048
DEFAULT_PORT = 5432
HOST_ERROR = "The database host could not be reached or is not allowed."


class UnsafeConnectionError(ValueError):
  pass


@dataclass(frozen=True)
class ValidatedTarget:
  url: URL
  host: str
  port: int
  database: str
  hostaddr: str


def _is_public_address(address: str) -> bool:
  ip = ipaddress.ip_address(address.split("%")[0])
  mapped = getattr(ip, "ipv4_mapped", None)
  if mapped is not None:
    ip = mapped
  return ip.is_global and not ip.is_multicast


def _parse(connection_string: str) -> URL:
  value = connection_string.strip()
  if not value:
    raise UnsafeConnectionError("A connection string is required.")
  if len(value) > MAX_CONNECTION_STRING_LENGTH:
    raise UnsafeConnectionError("The connection string is too long.")
  if value.startswith("postgres://"):
    value = "postgresql://" + value[len("postgres://"):]
  try:
    return make_url(value)
  except (ArgumentError, ValueError):
    raise UnsafeConnectionError("The connection string could not be parsed.") from None


def _validated_query(url: URL) -> dict[str, str]:
  unknown = sorted(set(url.query) - ALLOWED_QUERY_PARAMS)
  if unknown:
    raise UnsafeConnectionError(f"Unsupported connection parameters: {', '.join(unknown)}.")

  sslmode = url.query.get("sslmode", "require")
  if sslmode not in SECURE_SSL_MODES:
    raise UnsafeConnectionError("SSL is required: use sslmode=require or stronger.")
  query = {"sslmode": sslmode}

  channel_binding = url.query.get("channel_binding")
  if channel_binding is not None:
    if channel_binding not in CHANNEL_BINDING_MODES:
      raise UnsafeConnectionError("Unsupported channel_binding value.")
    query["channel_binding"] = channel_binding
  return query


def _resolve_public_address(host: str, port: int, resolver) -> str:
  try:
    infos = resolver(host, port, type=socket.SOCK_STREAM)
  except (OSError, ValueError):
    raise UnsafeConnectionError(HOST_ERROR) from None

  addresses = {info[4][0] for info in infos}
  if not addresses or not all(_is_public_address(a) for a in addresses):
    raise UnsafeConnectionError(HOST_ERROR)

  ipv4 = sorted(a for a in addresses if ":" not in a)
  return ipv4[0] if ipv4 else sorted(addresses)[0]


def validate_connection_string(connection_string: str, resolver=socket.getaddrinfo) -> ValidatedTarget:
  url = _parse(connection_string)

  if url.drivername not in ALLOWED_DRIVERS:
    raise UnsafeConnectionError("Only PostgreSQL connections are supported.")
  if not url.host or url.host.startswith("/"):
    raise UnsafeConnectionError("A database host name is required.")
  if not url.username or not url.password or not url.database:
    raise UnsafeConnectionError("The connection string must include a user, password, and database name.")

  query = _validated_query(url)
  port = url.port or DEFAULT_PORT
  hostaddr = _resolve_public_address(url.host, port, resolver)

  return ValidatedTarget(
    url=url.set(drivername="postgresql", port=port, query=query),
    host=url.host,
    port=port,
    database=url.database,
    hostaddr=hostaddr,
  )