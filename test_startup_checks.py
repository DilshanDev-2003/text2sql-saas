import pytest
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
  monkeypatch.delenv("DATABASE_URL")
  with patch.object(sc, "get_token", return_value="hf_x"):
    assert len(sc.check_environment()) == 2


def test_environment_reports_missing_hf_token(env):
  with patch.object(sc, "get_token", return_value=None):
    assert len(sc.check_environment()) == 1


def test_empty_schema_rejected():
  assert sc.check_schema({})


def test_control_plane_tables_in_generation_database_rejected():
  assert sc.check_schema({"api_keys": {}, "oauth_identities": {}, "singer": {}})


def test_customer_schema_with_users_table_is_allowed():
  assert sc.check_schema({"users": {}, "orders": {}}) == []


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