"""AES-256-GCM secret vault.

Mirrors the integrity guarantees of the original platform: secrets are sealed
with an authenticated cipher and the master key never leaves the process. The
sealed payload contains only ciphertext, nonce and auth tag (all base64).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

_NONCE_BYTES = 12


@dataclass(frozen=True)
class SealedSecret:
    ciphertext: str
    nonce: str
    auth_tag: str

    def to_dict(self) -> dict[str, str]:
        return {"ciphertext": self.ciphertext, "nonce": self.nonce, "authTag": self.auth_tag}

    @classmethod
    def from_dict(cls, payload: dict[str, str]) -> "SealedSecret":
        return cls(
            ciphertext=payload["ciphertext"],
            nonce=payload["nonce"],
            auth_tag=payload["authTag"],
        )


def _master_key() -> bytes:
    key = settings.VAULT_MASTER_KEY
    if len(key) != 32:
        raise ValueError("Vault master key must be exactly 32 bytes (AES-256).")
    return key


def encrypt_secret(plaintext: str) -> SealedSecret:
    aesgcm = AESGCM(_master_key())
    nonce = AESGCM.generate_key(bit_length=128)[:_NONCE_BYTES]
    sealed = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    # AESGCM appends the 16-byte tag to the ciphertext; split for parity.
    ciphertext, tag = sealed[:-16], sealed[-16:]
    return SealedSecret(
        ciphertext=base64.b64encode(ciphertext).decode("ascii"),
        nonce=base64.b64encode(nonce).decode("ascii"),
        auth_tag=base64.b64encode(tag).decode("ascii"),
    )


def decrypt_secret(sealed: SealedSecret) -> str:
    aesgcm = AESGCM(_master_key())
    nonce = base64.b64decode(sealed.nonce)
    ciphertext = base64.b64decode(sealed.ciphertext)
    tag = base64.b64decode(sealed.auth_tag)
    plaintext = aesgcm.decrypt(nonce, ciphertext + tag, None)
    return plaintext.decode("utf-8")
