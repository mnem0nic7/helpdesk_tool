from __future__ import annotations

import hashlib

from cryptography.fernet import Fernet

from .config import settings


class SecretCipher:
    def __init__(self) -> None:
        self._fernet = Fernet(settings.platform_encryption_key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")

    def fingerprint(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


cipher = SecretCipher()
