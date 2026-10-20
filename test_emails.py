import pytest
from pydantic import TypeAdapter, ValidationError

from app.auth.emails import NormalizedEmail, normalize_email


def test_normalize_lowercases_and_strips():
  assert normalize_email("  Mixed@Example.COM ") == "mixed@example.com"


def test_normalized_email_type_lowercases():
  assert TypeAdapter(NormalizedEmail).validate_python("Mixed@Example.COM") == "mixed@example.com"


def test_normalized_email_type_rejects_invalid_addresses():
  with pytest.raises(ValidationError):
    TypeAdapter(NormalizedEmail).validate_python("not-an-email")