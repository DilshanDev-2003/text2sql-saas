from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def check(model_error=None, control_plane_error=None):
  with patch(
    "app.api.routes.health.get_model_and_tokenizer",
    side_effect=model_error,
    return_value=(object(), object()),
  ), patch("app.api.routes.health.get_control_plane_engine") as engine:
    if control_plane_error:
      engine.return_value.connect.side_effect = control_plane_error
    return TestClient(app).get("/health")


def test_health_ok():
  r = check()

  assert r.status_code == 200
  assert r.json() == {"status": "ok", "model": "ok", "control_plane": "ok"}


def test_health_reports_missing_model():
  r = check(model_error=RuntimeError("not loaded"))

  assert r.status_code == 200
  assert r.json() == {"status": "degraded", "model": "unavailable", "control_plane": "ok"}


def test_health_reports_unreachable_control_plane():
  r = check(control_plane_error=RuntimeError("down"))

  assert r.status_code == 200
  assert r.json() == {"status": "degraded", "model": "ok", "control_plane": "unreachable"}