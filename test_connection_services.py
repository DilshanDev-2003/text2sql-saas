from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.encryption import LocalAesGcmEncryptor
from app.db.connection_safety import UnsafeConnectionError, validate_connection_string
from app.services import connections
from app.services.connection_cache import ConnectionCache

CONNECTION_STRING = "postgresql://u:secretpw@db.example.com/appdb"


def _resolver(host, port, type=0):
  return [(0, 0, 0, "", ("93.184.216.34", port))]


TARGET = validate_connection_string(CONNECTION_STRING, _resolver)
PLAINTEXT = TARGET.url.render_as_string(hide_password=False)
ENCRYPTOR = LocalAesGcmEncryptor({1: b"1" * 32}, 1)


def result(first=None, one=None, rows=None):
  r = MagicMock()
  r.first.return_value = first
  r.one.return_value = one
  r.all.return_value = rows or []
  return r


def control_plane(read_results=(), write_results=()):
  engine = MagicMock()
  read = engine.connect.return_value.__enter__.return_value
  write = engine.begin.return_value.__enter__.return_value
  read.execute.side_effect = list(read_results)
  write.execute.side_effect = list(write_results)
  return engine, read, write


def usage(total=0, same_name=0):
  return result(one=SimpleNamespace(total=total, same_name=same_name))


@pytest.fixture
def mocks():
  engine = MagicMock()
  with patch("app.services.connections.validate_connection_string", return_value=TARGET) as validate, \
       patch("app.services.connections.build_customer_engine", return_value=engine) as build, \
       patch("app.services.connections.get_live_schema", return_value={"singer": {}}) as introspect:
    yield SimpleNamespace(engine=engine, validate=validate, build=build, introspect=introspect)


def test_create_saves_encrypted_connection_and_caches_engine(mocks):
  cp, read, write = control_plane(
    [usage()], [result(one=SimpleNamespace(id=7, created_at="now"))]
  )
  cache = ConnectionCache()

  created = connections.create_connection(cp, 3, " Production ", CONNECTION_STRING, ENCRYPTOR, cache)

  assert created == {
    "id": 7,
    "name": "Production",
    "host": "db.example.com",
    "database_name": "appdb",
    "created_at": "now",
  }
  params = write.execute.call_args.args[1]
  assert params["name"] == "Production"
  assert b"secretpw" not in params["ciphertext"]
  assert ENCRYPTOR.decrypt(params["ciphertext"], params["key_version"], "user:3") == PLAINTEXT
  assert cache.get(7).engine is mocks.engine
  assert cache.get(7).schema == {"singer": {}}


def test_create_rejects_when_limit_reached(mocks):
  cp, _, _ = control_plane([usage(total=5)])

  with pytest.raises(connections.ConnectionLimitReached):
    connections.create_connection(cp, 3, "Prod", CONNECTION_STRING, ENCRYPTOR, ConnectionCache())

  mocks.validate.assert_not_called()


def test_create_rejects_taken_name_before_connecting(mocks):
  cp, _, _ = control_plane([usage(same_name=1)])

  with pytest.raises(connections.ConnectionNameTaken):
    connections.create_connection(cp, 3, "Prod", CONNECTION_STRING, ENCRYPTOR, ConnectionCache())

  mocks.build.assert_not_called()


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_create_rejects_blank_or_overlong_name(mocks, name):
  cp, _, _ = control_plane()

  with pytest.raises(connections.InvalidConnectionName):
    connections.create_connection(cp, 3, name, CONNECTION_STRING, ENCRYPTOR, ConnectionCache())


def test_create_propagates_unsafe_connection_error(mocks):
  mocks.validate.side_effect = UnsafeConnectionError("bad host")
  cp, _, _ = control_plane([usage()])

  with pytest.raises(UnsafeConnectionError):
    connections.create_connection(cp, 3, "Prod", CONNECTION_STRING, ENCRYPTOR, ConnectionCache())

  mocks.build.assert_not_called()


def test_create_reports_connection_failure_and_disposes_engine(mocks):
  mocks.introspect.side_effect = OperationalError("SELECT 1", {}, Exception("boom"))
  cp, _, write = control_plane([usage()])
  cache = ConnectionCache()

  with pytest.raises(connections.ConnectionTestFailed):
    connections.create_connection(cp, 3, "Prod", CONNECTION_STRING, ENCRYPTOR, cache)

  mocks.engine.dispose.assert_called_once()
  write.execute.assert_not_called()


def test_create_rejects_database_with_no_tables(mocks):
  mocks.introspect.return_value = {}
  cp, _, write = control_plane([usage()])

  with pytest.raises(connections.ConnectionTestFailed):
    connections.create_connection(cp, 3, "Prod", CONNECTION_STRING, ENCRYPTOR, ConnectionCache())

  mocks.engine.dispose.assert_called_once()
  write.execute.assert_not_called()


def test_create_maps_unique_violation_to_name_taken_and_disposes(mocks):
  cp, _, _ = control_plane([usage()], [IntegrityError("INSERT", {}, Exception("duplicate"))])

  with pytest.raises(connections.ConnectionNameTaken):
    connections.create_connection(cp, 3, "Prod", CONNECTION_STRING, ENCRYPTOR, ConnectionCache())

  mocks.engine.dispose.assert_called_once()


def test_list_returns_public_fields_only():
  row = SimpleNamespace(
    id=1,
    name="A",
    host="h",
    database_name="d",
    created_at="c",
    last_connected_at=None,
    encrypted_connection_string=b"secret",
  )
  cp, read, _ = control_plane([result(rows=[row])])

  listed = connections.list_connections(cp, 3)

  assert read.execute.call_args.args[1] == {"user_id": 3}
  assert len(listed) == 1
  assert set(listed[0]) == {"id", "name", "host", "database_name", "created_at", "last_connected_at"}


def test_delete_removes_row_and_evicts_cached_engine():
  cp, _, write = control_plane(write_results=[result(first=(7,))])
  cache = ConnectionCache()
  cached_engine = MagicMock()
  cache.put(7, cached_engine, {})

  connections.delete_connection(cp, cache, 3, 7)

  assert write.execute.call_args.args[1] == {"id": 7, "user_id": 3}
  cached_engine.dispose.assert_called_once()
  assert cache.get(7) is None


def test_delete_of_missing_or_foreign_connection_is_not_found():
  cp, _, _ = control_plane(write_results=[result(first=None)])
  cache = ConnectionCache()
  cached_engine = MagicMock()
  cache.put(7, cached_engine, {})

  with pytest.raises(connections.ConnectionNotFound):
    connections.delete_connection(cp, cache, 3, 7)

  cached_engine.dispose.assert_not_called()


def test_get_entry_returns_cached_engine_after_ownership_check(mocks):
  row = SimpleNamespace(encrypted_connection_string=b"unused", key_version=1)
  cp, read, write = control_plane([result(first=row)])
  cache = ConnectionCache()
  cached = cache.put(7, MagicMock(), {"singer": {}})

  entry = connections.get_connection_entry(cp, cache, ENCRYPTOR, 3, 7)

  assert entry is cached
  assert read.execute.call_args.args[1] == {"id": 7, "user_id": 3}
  mocks.validate.assert_not_called()
  write.execute.assert_not_called()


def test_get_entry_for_unowned_connection_is_not_found_even_if_cached(mocks):
  cp, _, _ = control_plane([result(first=None)])
  cache = ConnectionCache()
  cache.put(7, MagicMock(), {})

  with pytest.raises(connections.ConnectionNotFound):
    connections.get_connection_entry(cp, cache, ENCRYPTOR, 3, 7)


def test_get_entry_rebuilds_on_cache_miss_and_revalidates(mocks):
  encrypted = ENCRYPTOR.encrypt(PLAINTEXT, "user:3")
  row = SimpleNamespace(encrypted_connection_string=encrypted.ciphertext, key_version=encrypted.key_version)
  cp, _, write = control_plane([result(first=row)], [result()])
  cache = ConnectionCache()

  entry = connections.get_connection_entry(cp, cache, ENCRYPTOR, 3, 7)

  mocks.validate.assert_called_once_with(PLAINTEXT)
  assert entry.engine is mocks.engine
  assert cache.get(7) is entry
  assert write.execute.call_args.args[1]["id"] == 7


def test_get_entry_with_ciphertext_bound_to_another_user_is_unreadable(mocks):
  encrypted = ENCRYPTOR.encrypt(PLAINTEXT, "user:99")
  row = SimpleNamespace(encrypted_connection_string=encrypted.ciphertext, key_version=encrypted.key_version)
  cp, _, _ = control_plane([result(first=row)])

  with pytest.raises(connections.ConnectionUnreadable):
    connections.get_connection_entry(cp, ConnectionCache(), ENCRYPTOR, 3, 7)

  mocks.validate.assert_not_called()


def test_get_entry_disposes_engine_when_introspection_fails(mocks):
  mocks.introspect.side_effect = OperationalError("SELECT 1", {}, Exception("boom"))
  encrypted = ENCRYPTOR.encrypt(PLAINTEXT, "user:3")
  row = SimpleNamespace(encrypted_connection_string=encrypted.ciphertext, key_version=encrypted.key_version)
  cp, _, _ = control_plane([result(first=row)])
  cache = ConnectionCache()

  with pytest.raises(connections.ConnectionTestFailed):
    connections.get_connection_entry(cp, cache, ENCRYPTOR, 3, 7)

  mocks.engine.dispose.assert_called_once()
  assert cache.get(7) is None