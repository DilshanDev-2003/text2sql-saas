import base64

import pytest

from app.core.encryption import DecryptionError, LocalAesGcmEncryptor, get_encryptor

KEY_1 = b"1" * 32
KEY_2 = b"2" * 32


def make(keys=None, current=1):
  return LocalAesGcmEncryptor(keys or {1: KEY_1}, current)


def test_round_trip():
  enc = make()
  value = enc.encrypt("postgresql://u:p@h/db", "user:1")
  assert enc.decrypt(value.ciphertext, value.key_version, "user:1") == "postgresql://u:p@h/db"


def test_ciphertext_does_not_contain_plaintext():
  value = make().encrypt("postgresql://u:secretpw@h/db", "user:1")
  assert b"secretpw" not in value.ciphertext


def test_same_plaintext_encrypts_differently_each_time():
  enc = make()
  assert enc.encrypt("x", "c").ciphertext != enc.encrypt("x", "c").ciphertext


def test_wrong_context_fails():
  enc = make()
  value = enc.encrypt("secret", "user:1")
  with pytest.raises(DecryptionError):
    enc.decrypt(value.ciphertext, value.key_version, "user:2")


def test_tampered_ciphertext_fails():
  enc = make()
  value = enc.encrypt("secret", "user:1")
  tampered = bytearray(value.ciphertext)
  tampered[-1] ^= 1
  with pytest.raises(DecryptionError):
    enc.decrypt(bytes(tampered), value.key_version, "user:1")


def test_old_key_version_still_decrypts_after_rotation():
  old = make({1: KEY_1}, current=1).encrypt("secret", "user:1")
  rotated = make({1: KEY_1, 2: KEY_2}, current=2)
  assert rotated.encrypt("x", "user:1").key_version == 2
  assert rotated.decrypt(old.ciphertext, old.key_version, "user:1") == "secret"


def test_unknown_key_version_fails():
  with pytest.raises(DecryptionError):
    make().decrypt(b"x" * 40, 99, "c")


def test_accepts_memoryview_from_database_driver():
  enc = make()
  value = enc.encrypt("secret", "user:1")
  assert enc.decrypt(memoryview(value.ciphertext), value.key_version, "user:1") == "secret"


def test_rejects_wrong_key_length():
  with pytest.raises(ValueError):
    LocalAesGcmEncryptor({1: b"short"}, 1)


def test_rejects_unknown_current_version():
  with pytest.raises(ValueError):
    LocalAesGcmEncryptor({1: KEY_1}, 2)


def test_factory_builds_local_encryptor(monkeypatch):
  monkeypatch.setenv("ENCRYPTION_BACKEND", "local")
  monkeypatch.setenv("ENCRYPTION_KEYS", "1:" + base64.b64encode(KEY_1).decode())
  monkeypatch.setenv("ENCRYPTION_KEY_VERSION", "1")
  assert isinstance(get_encryptor(), LocalAesGcmEncryptor)


def test_factory_rejects_unknown_backend(monkeypatch):
  monkeypatch.setenv("ENCRYPTION_BACKEND", "carrier-pigeon")
  with pytest.raises(ValueError):
    get_encryptor()