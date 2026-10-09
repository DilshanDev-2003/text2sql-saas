import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

import app.main as app_module
from app.main import app
from app.auth.security import hash_password


@pytest.fixture(autouse=True)
def reset_limiter_storage():
  app_module.limiter._storage.reset()
  yield
  app_module.limiter._storage.reset()


@pytest.fixture
def client():
  return TestClient(app)


@pytest.fixture
def fake_user():
  return {"id": 1, "email": "test@example.com", "password": "testpass123"}


def test_signup_success(client, fake_user):
  with patch("app.auth.routes.get_control_plane_engine") as mock_engine:
    conn = mock_engine.return_value.begin.return_value.__enter__.return_value
    conn.execute.return_value.first.return_value = None
    conn.execute.return_value.scalar_one.return_value = fake_user["id"]

    r = client.post("/signup", json={"email": fake_user["email"], "password": fake_user["password"]})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_signup_duplicate_email_returns_409(client, fake_user):
  with patch("app.auth.routes.get_control_plane_engine") as mock_engine:
    conn = mock_engine.return_value.begin.return_value.__enter__.return_value
    conn.execute.return_value.first.return_value = (fake_user["id"],)

    r = client.post("/signup", json={"email": fake_user["email"], "password": fake_user["password"]})
    assert r.status_code == 409


def test_login_success(client, fake_user):
  hashed = hash_password(fake_user["password"])

  with patch("app.auth.routes.get_control_plane_engine") as mock_engine:
    conn = mock_engine.return_value.connect.return_value.__enter__.return_value
    row = type("Row", (), {"id": fake_user["id"], "password_hash": hashed})()
    conn.execute.return_value.first.return_value = row

    r = client.post("/login", json={"email": fake_user["email"], "password": fake_user["password"]})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_login_wrong_password_returns_401(client, fake_user):
  hashed = hash_password(fake_user["password"])

  with patch("app.auth.routes.get_control_plane_engine") as mock_engine:
    conn = mock_engine.return_value.connect.return_value.__enter__.return_value
    row = type("Row", (), {"id": fake_user["id"], "password_hash": hashed})()
    conn.execute.return_value.first.return_value = row

    r = client.post("/login", json={"email": fake_user["email"], "password": "wrongpassword"})
    assert r.status_code == 401


def test_login_unknown_email_returns_401(client):
  with patch("app.auth.routes.get_control_plane_engine") as mock_engine:
    conn = mock_engine.return_value.connect.return_value.__enter__.return_value
    conn.execute.return_value.first.return_value = None

    r = client.post("/login", json={"email": "nobody@example.com", "password": "whatever"})
    assert r.status_code == 401


def test_me_with_valid_token(client, fake_user):
  with patch("app.auth.routes.get_control_plane_engine") as mock_engine:
    conn = mock_engine.return_value.begin.return_value.__enter__.return_value
    conn.execute.return_value.first.return_value = None
    conn.execute.return_value.scalar_one.return_value = fake_user["id"]

    signup = client.post("/signup", json={"email": fake_user["email"], "password": fake_user["password"]})
    token = signup.json()["access_token"]

  r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
  assert r.status_code == 200
  assert r.json()["user_id"] == fake_user["id"]


def test_me_missing_header_returns_422(client):
  r = client.get("/me")
  assert r.status_code == 422


def test_me_garbage_token_returns_401(client):
  r = client.get("/me", headers={"Authorization": "Bearer garbage.token.value"})
  assert r.status_code == 401