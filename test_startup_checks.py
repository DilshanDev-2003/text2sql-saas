import pytest
import base64
from unittest.mock import patch

from app.core import startup_checks as sc


@pytest.fixture
def env(monkeypatch):
  for name in sc.REQUIRED_ENV_VARS:
    monkeypatch.setenv(name, "x")


def test_environment_ok(env):
  with patch.object(sc, "get_token", return_value="hf_x"):
    assert sc.check_environment() == []


def test_environment_reports_every_missing_variable(env, monkeypatch):
  monkeypatch.delenv("JWT_SECRET")
  monkeypatch.delenv("ENCRYPTION_KEYS")
  with patch.object(sc, "get_token", return_value="hf_x"):
    assert len(sc.check_environment()) == 2


def test_environment_reports_missing_hf_token(env):
  with patch.object(sc, "get_token", return_value=None):
    assert len(sc.check_environment()) == 1


def test_control_plane_missing_tables_reported():
  with patch.object(sc, "inspect") as mock_inspect:
    mock_inspect.return_value.get_table_names.return_value = ["users"]
    problems = sc.check_control_plane(object())
  assert "api_keys" in problems[0] and "tenants" in problems[0]


def test_control_plane_unreachable_reported():
  with patch.object(sc, "inspect", side_effect=RuntimeError("boom")):
    assert sc.check_control_plane(object())


def test_raise_if_problems_lists_everything():
  with pytest.raises(sc.StartupError) as exc:
    sc.raise_if_problems(["one", "two"])
  assert "one" in str(exc.value) and "two" in str(exc.value)


def test_raise_if_problems_noop_when_empty():
  sc.raise_if_problems([])

def valid_encryption_env(monkeypatch):
  monkeypatch.setenv("ENCRYPTION_BACKEND", "local")
  monkeypatch.setenv("ENCRYPTION_KEYS", "1:" + base64.b64encode(b"k" * 32).decode())
  monkeypatch.setenv("ENCRYPTION_KEY_VERSION", "1")


def test_encryption_ok(monkeypatch):
  valid_encryption_env(monkeypatch)
  assert sc.check_encryption() == []


def test_encryption_problem_never_reveals_the_key(monkeypatch):
  raw_key = base64.b64encode(b"k" * 32).decode()
  monkeypatch.setenv("ENCRYPTION_BACKEND", "local")
  monkeypatch.setenv("ENCRYPTION_KEYS", raw_key)
  monkeypatch.setenv("ENCRYPTION_KEY_VERSION", "1")

  problems = sc.check_encryption()

  assert len(problems) == 1
  assert raw_key not in problems[0]


def test_encryption_rejects_a_key_of_the_wrong_length(monkeypatch):
  monkeypatch.setenv("ENCRYPTION_BACKEND", "local")
  monkeypatch.setenv("ENCRYPTION_KEYS", "1:" + base64.b64encode(b"short").decode())
  monkeypatch.setenv("ENCRYPTION_KEY_VERSION", "1")

  assert len(sc.check_encryption()) == 1


def test_encryption_rejects_a_version_without_a_key(monkeypatch):
  valid_encryption_env(monkeypatch)
  monkeypatch.setenv("ENCRYPTION_KEY_VERSION", "2")

  assert len(sc.check_encryption()) == 1


def test_encryption_rejects_an_unknown_backend(monkeypatch):
  valid_encryption_env(monkeypatch)
  monkeypatch.setenv("ENCRYPTION_BACKEND", "carrier-pigeon")

  assert len(sc.check_encryption()) == 1  