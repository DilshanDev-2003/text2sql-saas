from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.main as app_module
from app.main import app
from app.auth import verification
from app.auth.security import hash_token


@pytest.fixture(autouse=True)
def reset_limiter_storage():
  app_module.limiter._storage.reset()
  yield
  app_module.limiter._storage.reset()


@pytest.fixture
def client():
  return TestClient(app)

@pytest.fixture(autouse=True)
def no_real_control_plane():
  with patch("app.auth.routes.get_control_plane_engine"):
    yield


def _engine_with(results):
  engine = MagicMock()
  conn = engine.begin.return_value.__enter__.return_value
  conn.execute.side_effect = results
  return engine, conn


def _result(first=None):
  result = MagicMock()
  result.first.return_value = first
  return result


def test_create_token_stores_only_hash_and_clears_old_tokens():
  conn = MagicMock()
  token = verification.create_verification_token(conn, 1)

  delete_call, insert_call = conn.execute.call_args_list
  assert "DELETE" in str(delete_call.args[0])

  params = insert_call.args[1]
  assert params["token_hash"] == hash_token(token)
  assert token not in params.values()

  remaining = params["expires_at"] - datetime.now(timezone.utc)
  assert timedelta(hours=23) < remaining <= timedelta(hours=24)


def test_send_email_contains_link_with_token():
  sender = MagicMock()
  with patch("app.auth.verification.get_email_sender", return_value=sender):
    verification.send_verification_email("a@example.com", "tok123")

  to, subject, body = sender.send.call_args.args
  assert to == "a@example.com"
  assert "verify-email?token=tok123" in body


def test_send_failure_is_swallowed():
  sender = MagicMock()
  sender.send.side_effect = RuntimeError("mail provider down")
  with patch("app.auth.verification.get_email_sender", return_value=sender):
    verification.send_verification_email("a@example.com", "tok123")


def test_verify_valid_token_marks_user_and_clears_tokens():
  engine, conn = _engine_with([_result(first=(4,)), _result(), _result()])

  assert verification.verify_email_token(engine, "tok") is True
  assert conn.execute.call_count == 3
  assert "UPDATE users" in str(conn.execute.call_args_list[1].args[0])
  assert "DELETE" in str(conn.execute.call_args_list[2].args[0])


def test_verify_unknown_or_expired_token_changes_nothing():
  engine, conn = _engine_with([_result(first=None)])

  assert verification.verify_email_token(engine, "tok") is False
  assert conn.execute.call_count == 1


def test_resend_for_unknown_or_verified_email_sends_nothing():
  engine, _ = _engine_with([_result(first=None)])

  with patch("app.auth.verification.send_verification_email") as send:
    verification.resend_verification(engine, "nobody@example.com")

  send.assert_not_called()


def test_resend_for_unverified_user_sends_new_token():
  engine, _ = _engine_with([_result(first=(4,))])

  with patch("app.auth.verification.create_verification_token", return_value="newtok"), \
       patch("app.auth.verification.send_verification_email") as send:
    verification.resend_verification(engine, "a@example.com")

  send.assert_called_once_with("a@example.com", "newtok")


def test_verify_email_route_success(client):
  with patch("app.auth.routes.verify_email_token", return_value=True):
    r = client.post("/auth/verify-email", json={"token": "tok"})

  assert r.status_code == 200
  assert r.json() == {"status": "verified"}


def test_verify_email_route_invalid_token_returns_400(client):
  with patch("app.auth.routes.verify_email_token", return_value=False):
    r = client.post("/auth/verify-email", json={"token": "tok"})

  assert r.status_code == 400


def test_resend_route_always_returns_ok(client):
  with patch("app.auth.routes.resend_verification") as resend:
    r = client.post("/auth/resend-verification", json={"email": "a@example.com"})

  assert r.status_code == 200
  assert r.json() == {"status": "ok"}
  resend.assert_called_once()


def test_resend_route_is_rate_limited(client):
  with patch("app.auth.routes.resend_verification"):
    statuses = [
      client.post("/auth/resend-verification", json={"email": "a@example.com"}).status_code
      for _ in range(6)
    ]

  assert statuses[:5] == [200] * 5
  assert statuses[5] == 429


def test_signup_sends_verification_email(client):
  with patch("app.auth.routes.get_control_plane_engine") as mock_engine, \
       patch("app.auth.routes.create_verification_token", return_value="tok"), \
       patch("app.auth.routes.send_verification_email") as send:
    conn = mock_engine.return_value.begin.return_value.__enter__.return_value
    conn.execute.return_value.first.return_value = None
    conn.execute.return_value.scalar_one.return_value = 1

    r = client.post("/signup", json={"email": "a@example.com", "password": "testpass123"})

  assert r.status_code == 200
  send.assert_called_once_with("a@example.com", "tok")

def test_resend_route_lowercases_email(client):
  with patch("app.auth.routes.resend_verification") as resend:
    client.post("/auth/resend-verification", json={"email": "Mixed@Example.COM"})

  assert resend.call_args.args[1] == "mixed@example.com"