import os
from dataclasses import dataclass
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import (
  get_encryption_backend,
  get_encryption_keys,
  get_encryption_key_version,
)

NONCE_BYTES = 12


class DecryptionError(Exception):
  pass


@dataclass(frozen=True)
class Encrypted:
  ciphertext: bytes
  key_version: int


class Encryptor(Protocol):
  def encrypt(self, plaintext: str, context: str) -> Encrypted: ...

  def decrypt(self, ciphertext: bytes, key_version: int, context: str) -> str: ...


class LocalAesGcmEncryptor:
  def __init__(self, keys: dict[int, bytes], current_version: int):
    if current_version not in keys:
      raise ValueError(f"No key configured for version {current_version}")
    for version, key in keys.items():
      if len(key) != 32:
        raise ValueError(f"Encryption key {version} must be 32 bytes")
    self._keys = keys
    self._current = current_version

  def encrypt(self, plaintext: str, context: str) -> Encrypted:
    nonce = os.urandom(NONCE_BYTES)
    body = AESGCM(self._keys[self._current]).encrypt(nonce, plaintext.encode(), context.encode())
    return Encrypted(nonce + body, self._current)

  def decrypt(self, ciphertext: bytes, key_version: int, context: str) -> str:
    key = self._keys.get(key_version)
    if key is None:
      raise DecryptionError(f"No key for version {key_version}")
    data = bytes(ciphertext)
    try:
      return AESGCM(key).decrypt(data[:NONCE_BYTES], data[NONCE_BYTES:], context.encode()).decode()
    except InvalidTag as e:
      raise DecryptionError("Could not decrypt value") from e


def get_encryptor() -> Encryptor:
  backend = get_encryption_backend()
  if backend == "local":
    return LocalAesGcmEncryptor(get_encryption_keys(), get_encryption_key_version())
  raise ValueError(f"Unknown ENCRYPTION_BACKEND: {backend}")