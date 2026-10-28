import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import require_user
from app.main import app
from app.services import connections
from app.services.connection_cache import ConnectionCache

BODY = {"connection_id": 7, "question": "average age of singers from France", "n": 1}
OUTPUT = {"sql": "SELECT 1", "result": [[1]]}


@pytest.fixture
def client():
  entry = SimpleNamespace(engine=MagicMock(), schema={"singer": {}})
  app.state.connection_cache = ConnectionCache()
  app.dependency_overrides[require_user] = lambda: 3
  with patch("app.api.routes.generate.get_model_and_tokenizer", return_value=(object(), object())), \
       patch("app.api.routes.generate.get_control_plane_engine"), \
       patch("app.api.routes.generate.get_encryptor"), \
       patch("app.api.routes.generate.get_sqlglot_dialect", return_value="postgres"), \
       patch("app.services.connections.get_connection_entry", return_value=entry):
    yield TestClient(app)
  app.dependency_overrides.clear()


def test_generate_success_uses_the_connections_engine_and_schema(client):
  with patch("app.api.routes.generate.generate_sql_final", return_value=OUTPUT) as generate:
    r = client.post("/generate", json=BODY)

  assert r.status_code == 200
  assert r.json() == OUTPUT
  kwargs = generate.call_args.kwargs
  assert kwargs["live_schema"] == {"singer": {}}
  assert kwargs["dialect"] == "postgres"
  assert kwargs["n"] == 1


def test_generate_checks_ownership_with_the_authenticated_user(client):
  entry = SimpleNamespace(engine=MagicMock(), schema={})
  with patch("app.services.connections.get_connection_entry", return_value=entry) as get_entry, \
       patch("app.api.routes.generate.generate_sql_final", return_value=OUTPUT):
    client.post("/generate", json=BODY)

  assert get_entry.call_args.args[3:] == (3, 7)


def test_generate_gpu_busy_returns_503(client):
  release = threading.Event()

  def slow_generate(*args, **kwargs):
    release.wait(timeout=5)
    return OUTPUT

  with patch("app.api.routes.generate.generate_sql_final", side_effect=slow_generate):
    results = []

    def call():
      results.append(client.post("/generate", json=BODY))

    first = threading.Thread(target=call)
    first.start()
    time.sleep(0.2)

    results.append(client.post("/generate", json=BODY))
    release.set()
    first.join()

  assert sorted(r.status_code for r in results) == [200, 503]
  busy = next(r for r in results if r.status_code == 503)
  assert busy.headers.get("Retry-After") == "5"


def test_generate_validation_failure_returns_422(client):
  output = {"sql": "SELECT bad", "result": None}
  with patch("app.api.routes.generate.generate_sql_final", return_value=output):
    r = client.post("/generate", json=BODY)

  assert r.status_code == 422
  assert r.json()["detail"]["attempted_sql"] == "SELECT bad"


def test_generate_db_unavailable_returns_503(client):
  output = {"sql": "SELECT x", "result": None, "failure_reason": "db_unavailable"}
  with patch("app.api.routes.generate.generate_sql_final", return_value=output):
    r = client.post("/generate", json=BODY)

  assert r.status_code == 503
  assert r.json()["detail"]["attempted_sql"] == "SELECT x"


@pytest.mark.parametrize(
  "error,status",
  [
    (connections.ConnectionNotFound("Connection not found."), 404),
    (connections.ConnectionTestFailed("no connect"), 400),
    (connections.ConnectionUnreadable("unreadable"), 409),
  ],
)
def test_generate_maps_connection_errors_and_never_generates(client, error, status):
  with patch("app.services.connections.get_connection_entry", side_effect=error), \
       patch("app.api.routes.generate.generate_sql_final") as generate:
    r = client.post("/generate", json=BODY)

  assert r.status_code == status
  assert r.json()["detail"] == str(error)
  generate.assert_not_called()


@pytest.mark.parametrize("n", [0, 11])
def test_generate_rejects_out_of_range_candidate_counts(client, n):
  with patch("app.api.routes.generate.generate_sql_final") as generate:
    r = client.post("/generate", json={**BODY, "n": n})

  assert r.status_code == 422
  assert any(error["loc"] == ["body", "n"] for error in r.json()["detail"])
  generate.assert_not_called()


def test_generate_requires_a_connection_id(client):
  with patch("app.api.routes.generate.generate_sql_final") as generate:
    r = client.post("/generate", json={"question": "q", "n": 1})

  assert r.status_code == 422
  assert any(error["loc"] == ["body", "connection_id"] for error in r.json()["detail"])
  generate.assert_not_called()


def test_generate_requires_a_valid_token(client):
  app.dependency_overrides.clear()
  r = client.post("/generate", json=BODY, headers={"Authorization": "Bearer garbage"})

  assert r.status_code == 401


def test_generate_is_rate_limited(client):
  with patch("app.api.routes.generate.generate_sql_final", return_value=OUTPUT):
    statuses = [client.post("/generate", json=BODY).status_code for _ in range(11)]

  assert statuses[:10] == [200] * 10
  assert statuses[10] == 429