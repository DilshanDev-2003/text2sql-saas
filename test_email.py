import logging

import pytest

from app.auth.security import generate_email_token, hash_token
from app.core.email_sender import ConsoleEmailSender, get_email_sender


def test_tokens_are_unique_and_long():
  tokens = {generate_email_token() for _ in range(100)}
  assert len(tokens) == 100
  assert all(len(t) >= 40 for t in tokens)


def test_hash_is_deterministic_and_differs_from_token():
  token = generate_email_token()
  assert hash_token(token) == hash_token(token)
  assert hash_token(token) != token
  assert len(hash_token(token)) == 64


def test_different_tokens_hash_differently():
  assert hash_token("a") != hash_token("b")


def test_console_sender_logs_message(caplog):
  with caplog.at_level(logging.INFO, logger="app.core.email_sender"):
    ConsoleEmailSender().send("a@example.com", "Subject", "Body text")
  assert "a@example.com" in caplog.text
  assert "Body text" in caplog.text


def test_factory_defaults_to_console(monkeypatch):
  monkeypatch.delenv("EMAIL_BACKEND", raising=False)
  assert isinstance(get_email_sender(), ConsoleEmailSender)


def test_factory_rejects_unknown_backend(monkeypatch):
  monkeypatch.setenv("EMAIL_BACKEND", "carrier-pigeon")
  with pytest.raises(ValueError):
    get_email_sender()