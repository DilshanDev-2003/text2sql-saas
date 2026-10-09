import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
from authlib.integrations.starlette_client import OAuthError
from starlette.responses import RedirectResponse

from app.main import app
from app.auth.security import decode_access_token
from app.auth.users import find_or_create_oauth_user, EmailAlreadyRegistered


@pytest.fixture
def client():
  return TestClient(app)


def fake_oauth(**google_attrs):
  oauth = MagicMock()
  for name, value in google_attrs.items():
    setattr(oauth.google, name, value)
  return oauth


def google_token(**userinfo_overrides):
  info = {"sub": "google-123", "email": "a@example.com", "email_verified": True}
  info.update(userinfo_overrides)
  return {"userinfo": info}


def _result(first=None, scalar=None):
  result = MagicMock()
  result.first.return_value = first
  result.scalar_one.return_value = scalar
  return result


def _engine_with(results):
  engine = MagicMock()
  conn = engine.begin.return_value.__enter__.return_value
  conn.execute.side_effect = results
  return engine, conn


def test_google_login_redirects_to_google(client):
  redirect = AsyncMock(return_value=RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth"))
  oauth = fake_oauth(authorize_redirect=redirect)

  with patch("app.auth.oauth_routes.get_oauth", return_value=oauth):
    r = client.get("/auth/google/login", follow_redirects=False)

  assert r.status_code == 307
  assert r.headers["location"].startswith("https://accounts.google.com")
  assert redirect.await_args.args[1].endswith("/auth/google/callback")


def test_callback_success_returns_token_for_user(client):
  oauth = fake_oauth(authorize_access_token=AsyncMock(return_value=google_token()))

  with patch("app.auth.oauth_routes.get_oauth", return_value=oauth), \
       patch("app.auth.oauth_routes.find_or_create_oauth_user", return_value=5) as find:
    r = client.get("/auth/google/callback")

  assert r.status_code == 200
  assert decode_access_token(r.json()["access_token"]) == 5
  find.assert_called_once_with("google", "google-123", "a@example.com")


def test_callback_oauth_error_returns_400(client):
  failing = AsyncMock(side_effect=OAuthError(error="access_denied"))
  oauth = fake_oauth(authorize_access_token=failing)

  with patch("app.auth.oauth_routes.get_oauth", return_value=oauth):
    r = client.get("/auth/google/callback")

  assert r.status_code == 400


def test_callback_unverified_email_returns_400_and_creates_nothing(client):
  oauth = fake_oauth(authorize_access_token=AsyncMock(return_value=google_token(email_verified=False)))

  with patch("app.auth.oauth_routes.get_oauth", return_value=oauth), \
       patch("app.auth.oauth_routes.find_or_create_oauth_user") as find:
    r = client.get("/auth/google/callback")

  assert r.status_code == 400
  find.assert_not_called()


def test_callback_missing_userinfo_returns_400(client):
  oauth = fake_oauth(authorize_access_token=AsyncMock(return_value={}))

  with patch("app.auth.oauth_routes.get_oauth", return_value=oauth):
    r = client.get("/auth/google/callback")

  assert r.status_code == 400


def test_callback_existing_password_account_returns_409(client):
  oauth = fake_oauth(authorize_access_token=AsyncMock(return_value=google_token()))

  with patch("app.auth.oauth_routes.get_oauth", return_value=oauth), \
       patch("app.auth.oauth_routes.find_or_create_oauth_user", side_effect=EmailAlreadyRegistered()):
    r = client.get("/auth/google/callback")

  assert r.status_code == 409


def test_existing_identity_returns_same_user():
  engine, conn = _engine_with([_result(first=(7,))])

  with patch("app.auth.users.get_control_plane_engine", return_value=engine):
    user_id = find_or_create_oauth_user("google", "google-123", "a@example.com")

  assert user_id == 7
  assert conn.execute.call_count == 1


def test_existing_email_without_identity_is_refused():
  engine, conn = _engine_with([_result(first=None), _result(first=(3,))])

  with patch("app.auth.users.get_control_plane_engine", return_value=engine):
    with pytest.raises(EmailAlreadyRegistered):
      find_or_create_oauth_user("google", "google-123", "a@example.com")

  assert conn.execute.call_count == 2


def test_new_user_is_created_with_linked_identity():
  engine, conn = _engine_with([_result(), _result(), _result(scalar=9), _result()])

  with patch("app.auth.users.get_control_plane_engine", return_value=engine):
    user_id = find_or_create_oauth_user("google", "google-123", "a@example.com")

  assert user_id == 9
  assert conn.execute.call_count == 4


def test_login_oauth_only_user_returns_401_not_500(client):
  with patch("app.auth.routes.get_control_plane_engine") as mock_engine:
    conn = mock_engine.return_value.connect.return_value.__enter__.return_value
    row = type("Row", (), {"id": 1, "password_hash": None})()
    conn.execute.return_value.first.return_value = row

    r = client.post("/login", json={"email": "a@example.com", "password": "whatever"})

  assert r.status_code == 401