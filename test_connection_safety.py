import socket

import pytest

from app.db.connection_safety import UnsafeConnectionError, validate_connection_string

PUBLIC = "93.184.216.34"
GOOD = "postgresql://u:p@db.example.com/appdb"


def resolver_for(*addresses):
  def resolve(host, port, type=0):
    return [(0, 0, 0, "", (address, port)) for address in addresses]

  return resolve


def validate(url, *addresses):
  return validate_connection_string(url, resolver_for(*(addresses or (PUBLIC,))))


def test_valid_connection_string_is_normalized():
  target = validate(GOOD)
  assert target.host == "db.example.com"
  assert target.port == 5432
  assert target.database == "appdb"
  assert target.hostaddr == PUBLIC
  assert target.url.drivername == "postgresql"
  assert target.url.query["sslmode"] == "require"


def test_postgres_scheme_alias_is_accepted():
  assert validate("postgres://u:p@db.example.com/appdb").url.drivername == "postgresql"


def test_driver_override_is_normalized():
  assert validate("postgresql+psycopg2://u:p@db.example.com/appdb").url.drivername == "postgresql"


def test_non_postgres_scheme_rejected():
  with pytest.raises(UnsafeConnectionError):
    validate("mysql://u:p@db.example.com/appdb")


@pytest.mark.parametrize(
  "url",
  [
    "postgresql://u:p@/appdb",
    "postgresql://db.example.com/appdb",
    "postgresql://u@db.example.com/appdb",
    "postgresql://u:p@db.example.com",
  ],
)
def test_missing_required_parts_rejected(url):
  with pytest.raises(UnsafeConnectionError):
    validate(url)


@pytest.mark.parametrize(
  "param",
  ["host=10.0.0.5", "hostaddr=10.0.0.5", "options=-c%20x", "sslcert=/etc/passwd"],
)
def test_unknown_query_parameters_rejected(param):
  with pytest.raises(UnsafeConnectionError):
    validate(f"{GOOD}?{param}")


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer"])
def test_weak_sslmode_rejected(mode):
  with pytest.raises(UnsafeConnectionError):
    validate(f"{GOOD}?sslmode={mode}")


@pytest.mark.parametrize("mode", ["require", "verify-full"])
def test_strong_sslmode_accepted(mode):
  assert validate(f"{GOOD}?sslmode={mode}").url.query["sslmode"] == mode


@pytest.mark.parametrize(
  "address",
  [
    "10.0.0.5",
    "127.0.0.1",
    "169.254.169.254",
    "192.168.1.1",
    "172.16.0.1",
    "100.64.0.1",
    "0.0.0.0",
    "224.0.0.1",
    "::1",
    "fe80::1",
    "fc00::1",
    "::ffff:127.0.0.1",
  ],
)
def test_private_and_reserved_addresses_rejected(address):
  with pytest.raises(UnsafeConnectionError):
    validate(GOOD, address)


def test_mixed_public_and_private_addresses_rejected():
  with pytest.raises(UnsafeConnectionError):
    validate(GOOD, PUBLIC, "10.0.0.5")


def test_unresolvable_host_gives_same_message_as_private_address():
  def failing(host, port, type=0):
    raise socket.gaierror("no such host")

  with pytest.raises(UnsafeConnectionError) as unresolved:
    validate_connection_string(GOOD, failing)
  with pytest.raises(UnsafeConnectionError) as private:
    validate(GOOD, "10.0.0.5")

  assert str(unresolved.value) == str(private.value)


def test_ipv4_address_is_preferred_for_pinning():
  assert validate(GOOD, "2606:4700::1111", PUBLIC).hostaddr == PUBLIC


@pytest.mark.parametrize(
  "url,addresses",
  [
    ("postgresql://u:secret@db.example.com:notaport/appdb", (PUBLIC,)),
    ("postgresql://u:secret@db.example.com/appdb", ("10.0.0.5",)),
    ("postgresql://u:secret@db.example.com/appdb?sslmode=disable", (PUBLIC,)),
  ],
)
def test_errors_never_contain_the_password(url, addresses):
  with pytest.raises(UnsafeConnectionError) as error:
    validate(url, *addresses)
  assert "secret" not in str(error.value)


@pytest.mark.parametrize("url", ["", "postgresql://u:p@db.example.com/" + "a" * 3000])
def test_empty_and_oversized_strings_rejected(url):
  with pytest.raises(UnsafeConnectionError):
    validate(url)