from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_MAGIC = b"TORYVAULT1"
_ITERATIONS = 600_000
_VERIFIER_MESSAGE = b"Dragon Tory Vault verifier v1"


class VaultNotConfiguredError(RuntimeError):
    pass


class VaultLockedError(RuntimeError):
    pass


class VaultPassphraseError(ValueError):
    pass


class ToryVault:
    def __init__(self, metadata_path: Path) -> None:
        self.metadata_path = Path(metadata_path)
        self._key: bytes | None = None

    @property
    def configured(self) -> bool:
        return self.metadata_path.is_file()

    @property
    def unlocked(self) -> bool:
        return self._key is not None

    def status(self) -> dict:
        return {
            "configured": self.configured,
            "unlocked": self.unlocked,
            "encryption": "AES-256-GCM",
            "kdf": f"PBKDF2-SHA256/{_ITERATIONS}",
            "passphrase_stored": False,
        }

    def _read_metadata(self) -> dict:
        if not self.configured:
            raise VaultNotConfiguredError("Сейф Тори ещё не настроен.")
        return json.loads(self.metadata_path.read_text(encoding="utf-8"))

    @staticmethod
    def _derive(passphrase: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=_ITERATIONS,
        )
        return kdf.derive(passphrase.encode("utf-8"))

    @staticmethod
    def _verifier(key: bytes) -> bytes:
        return hmac.new(
            key,
            _VERIFIER_MESSAGE,
            hashlib.sha256,
        ).digest()

    def setup(self, passphrase: str) -> dict:
        if self.configured:
            raise ValueError("Сейф Тори уже настроен.")
        if len(passphrase) < 12:
            raise ValueError(
                "Парольная фраза должна содержать не менее 12 символов."
            )
        salt = os.urandom(16)
        key = self._derive(passphrase, salt)
        metadata = {
            "version": 1,
            "salt": base64.b64encode(salt).decode("ascii"),
            "verifier": base64.b64encode(
                self._verifier(key)
            ).decode("ascii"),
            "iterations": _ITERATIONS,
        }
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.metadata_path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, self.metadata_path)
        self._key = key
        return self.status()

    def unlock(self, passphrase: str) -> dict:
        metadata = self._read_metadata()
        salt = base64.b64decode(metadata["salt"])
        expected = base64.b64decode(metadata["verifier"])
        key = self._derive(passphrase, salt)
        if not hmac.compare_digest(self._verifier(key), expected):
            raise VaultPassphraseError("Неверная парольная фраза.")
        self._key = key
        return self.status()

    def lock(self) -> dict:
        self._key = None
        return self.status()

    def _require_key(self) -> bytes:
        if not self.configured:
            raise VaultNotConfiguredError("Сейф Тори ещё не настроен.")
        if self._key is None:
            raise VaultLockedError("Сейф Тори заблокирован.")
        return self._key

    @staticmethod
    def is_encrypted(path: Path) -> bool:
        if not path.is_file():
            return False
        with path.open("rb") as source:
            return source.read(len(_MAGIC)) == _MAGIC

    def encrypt_file(self, path: Path, *, aad: bytes) -> None:
        if self.is_encrypted(path):
            return
        key = self._require_key()
        plaintext = path.read_bytes()
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
        temp = path.with_suffix(path.suffix + ".vaulttmp")
        temp.write_bytes(_MAGIC + nonce + ciphertext)
        os.replace(temp, path)

    def decrypt_file(self, path: Path, *, aad: bytes) -> None:
        if not self.is_encrypted(path):
            return
        plaintext = self.decrypt_bytes(path.read_bytes(), aad=aad)
        temp = path.with_suffix(path.suffix + ".vaulttmp")
        temp.write_bytes(plaintext)
        os.replace(temp, path)

    def decrypt_bytes(self, payload: bytes, *, aad: bytes) -> bytes:
        key = self._require_key()
        if not payload.startswith(_MAGIC):
            return payload
        offset = len(_MAGIC)
        nonce = payload[offset : offset + 12]
        ciphertext = payload[offset + 12 :]
        return AESGCM(key).decrypt(nonce, ciphertext, aad)

    def materialize(
        self,
        source: Path,
        destination: Path,
        *,
        aad: bytes,
    ) -> None:
        if not self.is_encrypted(source):
            raise ValueError("Файл не зашифрован.")
        destination.write_bytes(
            self.decrypt_bytes(source.read_bytes(), aad=aad)
        )
