from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.auth.dependencies import require_verified_user


@contextmanager
def control_plane_returning(row):
  with patch("app.auth.dependencies.get_control_plane_engine") as engine:
    engine.return_value.connect.return_value.__enter__.return_value.execute.return_value.first.return_value = row
    yield


def test_verified_user_passes():
  row = SimpleNamespace(email_verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
  with control_plane_returning(row):
    assert require_verified_user(3) == 3


def test_unverified_user_gets_403():
  with control_plane_returning(SimpleNamespace(email_verified_at=None)):
    with pytest.raises(HTTPException) as error:
      require_verified_user(3)

  assert error.value.status_code == 403


def test_unknown_user_gets_401():
  with control_plane_returning(None):
    with pytest.raises(HTTPException) as error:
      require_verified_user(3)

  assert error.value.status_code == 401