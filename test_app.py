import threading
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

import app as app_module
from app import app


@pytest.fixture(autouse=True)
def reset_limiter_storage():
  app_module.limiter._storage.reset()
  yield
  app_module.limiter._storage.reset()


@pytest.fixture
def client():
  app_module._engine = object()
  app_module._live_schema = {"tables": {}}
  app_module._dialect = "postgres"
  with patch("app.get_model_and_tokenizer", return_value=(object(), object())):
    yield TestClient(app)


def _mock_generate(*args, **kwargs):
  return {"sql": "SELECT 1", "result": [[1]]}


def test_schema_rate_limit(client):
  with patch("app.get_live_schema", return_value={"tables": {}}):
    for _ in range(60):
      r = client.get("/schema")
      assert r.status_code == 200

    r = client.get("/schema")
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_generate_gpu_busy_returns_503(client):
  release = threading.Event()

  def slow_generate(*args, **kwargs):
    release.wait(timeout=5)
    return {"sql": "SELECT 1", "result": [[1]]}

  with patch("app.generate_sql_final", side_effect=slow_generate):
    results = []

    def call():
      r = client.post("/generate", json={"question": "test", "n": 1})
      results.append(r)

    t1 = threading.Thread(target=call)
    t1.start()

    import time
    time.sleep(0.2)

    r2 = client.post("/generate", json={"question": "test", "n": 1})
    results.append(r2)

    release.set()
    t1.join()

    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 503]

    busy = next(r for r in results if r.status_code == 503)
    assert busy.headers.get("Retry-After") == "5"


def test_generate_success(client):
  with patch("app.generate_sql_final", side_effect=_mock_generate):
    r = client.post("/generate", json={"question": "average age", "n": 1})
    assert r.status_code == 200
    assert r.json()["sql"] == "SELECT 1"


def test_generate_validation_failure_returns_422(client):
  def fail_generate(*args, **kwargs):
    return {"sql": "SELECT bad", "result": None}

  with patch("app.generate_sql_final", side_effect=fail_generate):
    r = client.post("/generate", json={"question": "bad question", "n": 1})
    assert r.status_code == 422
    assert r.json()["detail"]["attempted_sql"] == "SELECT bad"


def test_generate_db_unavailable_returns_503(client):
  def fail_generate(*args, **kwargs):
    return {"sql": "SELECT x", "result": None, "failure_reason": "db_unavailable"}

  with patch("app.generate_sql_final", side_effect=fail_generate):
    r = client.post("/generate", json={"question": "any", "n": 1})
    assert r.status_code == 503
    assert "attempted_sql" in r.json()["detail"]