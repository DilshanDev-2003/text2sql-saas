from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import require_user, require_verified_user
from app.db.connection_safety import UnsafeConnectionError
from app.main import app
from app.services import connections
from app.services.connection_cache import ConnectionCache

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
BODY = {"name": "Prod", "connection_string": "postgresql://u:secretpw@db.example.com/appdb"}


def created():
  return {
    "id": 7,
    "name": "Prod",
    "host": "db.example.com",
    "database_name": "appdb",
    "created_at": CREATED,
  }


@pytest.fixture
def client():
  app.state.connection_cache = ConnectionCache()
  app.dependency_overrides[require_user] = lambda: 3
  app.dependency_overrides[require_verified_user] = lambda: 3
  with patch("app.api.routes.connections.get_control_plane_engine"), \
       patch("app.api.routes.connections.get_encryptor"):
    yield TestClient(app)
  app.dependency_overrides.clear()


def test_create_returns_201_without_echoing_the_connection_string(client):
  with patch("app.services.connections.create_connection", return_value=created()) as create:
    r = client.post("/connections", json=BODY)

  assert r.status_code == 201
  assert "secretpw" not in r.text
  assert set(r.json()) == {"id", "name", "host", "database_name", "created_at", "last_connected_at"}
  assert create.call_args.args[1:4] == (3, "Prod", BODY["connection_string"])


@pytest.mark.parametrize(
  "error,status",
  [
    (connections.InvalidConnectionName("bad name"), 422),
    (UnsafeConnectionError("bad host"), 400),
    (connections.ConnectionTestFailed("no connect"), 400),
    (connections.ConnectionNameTaken("taken"), 409),
    (connections.ConnectionLimitReached("limit"), 409),
  ],
)
def test_create_maps_errors_to_status_codes(client, error, status):
  with patch("app.services.connections.create_connection", side_effect=error):
    r = client.post("/connections", json=BODY)

  assert r.status_code == status
  assert r.json()["detail"] == str(error)


def test_list_returns_the_users_connections(client):
  items = [
    {
      "id": 1,
      "name": "A",
      "host": "h",
      "database_name": "d",
      "created_at": CREATED,
      "last_connected_at": None,
    }
  ]
  with patch("app.services.connections.list_connections", return_value=items) as listed:
    r = client.get("/connections")

  assert r.status_code == 200
  assert r.json()[0]["name"] == "A"
  assert listed.call_args.args[1] == 3


def test_delete_returns_204(client):
  with patch("app.services.connections.delete_connection") as delete:
    r = client.delete("/connections/7")

  assert r.status_code == 204
  assert delete.call_args.args[2:] == (3, 7)


def test_delete_missing_connection_returns_404(client):
  error = connections.ConnectionNotFound("Connection not found.")
  with patch("app.services.connections.delete_connection", side_effect=error):
    r = client.delete("/connections/7")

  assert r.status_code == 404
  assert r.json()["detail"] == "Connection not found."


def test_create_is_rate_limited(client):
  with patch("app.services.connections.create_connection", return_value=created()):
    responses = [client.post("/connections", json=BODY) for _ in range(11)]

  assert [r.status_code for r in responses[:10]] == [201] * 10
  assert responses[10].status_code == 429


def test_create_rejects_missing_fields(client):
  with patch("app.services.connections.create_connection") as create:
    r = client.post("/connections", json={"name": "Prod"})

  assert r.status_code == 422
  create.assert_not_called()


@pytest.mark.parametrize(
  "method,path",
  [("get", "/connections"), ("get", "/connections/7/schema"), ("post", "/connections"), ("delete", "/connections/7"),],
)
def test_connection_routes_reject_invalid_tokens(client, method, path):
  app.dependency_overrides.clear()
  r = client.request(method, path, json=BODY, headers={"Authorization": "Bearer garbage"})

  assert r.status_code == 401


def test_create_requires_a_verified_email(client):
  app.dependency_overrides.pop(require_verified_user)
  row = SimpleNamespace(email_verified_at=None)

  with patch("app.auth.dependencies.get_control_plane_engine") as engine, \
       patch("app.services.connections.create_connection") as create:
    engine.return_value.connect.return_value.__enter__.return_value.execute.return_value.first.return_value = row
    r = client.post("/connections", json=BODY)

  assert r.status_code == 403
  create.assert_not_called()

def test_schema_route_returns_the_connections_schema(client):
  entry = SimpleNamespace(schema={"singer": {"columns": []}})
  with patch("app.services.connections.get_connection_entry", return_value=entry) as get_entry:
    r = client.get("/connections/7/schema")

  assert r.status_code == 200
  assert r.json() == {"singer": {"columns": []}}
  assert get_entry.call_args.args[3:] == (3, 7)


def test_schema_route_unknown_connection_returns_404(client):
  error = connections.ConnectionNotFound("Connection not found.")
  with patch("app.services.connections.get_connection_entry", side_effect=error):
    r = client.get("/connections/7/schema")

  assert r.status_code == 404
  assert r.json()["detail"] == "Connection not found."  