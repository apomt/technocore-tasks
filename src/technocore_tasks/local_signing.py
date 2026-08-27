"""Local-only signing code. The hosted FastAPI application never imports this module."""

from __future__ import annotations

import base64
import os
import time

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_last_nonce = 0


class TechnocoreWriteError(RuntimeError):
    """An upstream write refusal whose response body must reach the local operator."""

    def __init__(self, status_code: int, reason_phrase: str, body: str):
        self.status_code = status_code
        self.reason_phrase = reason_phrase
        self.body = body
        super().__init__(status_code, reason_phrase, body)

    def __str__(self) -> str:
        header = f"Technocore HTTP {self.status_code} {self.reason_phrase}".rstrip()
        return f"{header}\nupstream response body:\n{self.body}"


def _b58encode(data: bytes) -> str:
    number = int.from_bytes(data, "big")
    chars = ""
    while number:
        number, remainder = divmod(number, 58)
        chars = ALPHABET[remainder] + chars
    zeros = len(data) - len(data.lstrip(b"\0"))
    return "1" * zeros + (chars or ("1" if not zeros else ""))


def load_seed() -> bytes:
    value = os.environ.get("SIGN_SEED")
    if not value:
        raise RuntimeError("SIGN_SEED is required for local signing commands")
    try:
        if len(value) == 64:
            seed = bytes.fromhex(value)
        else:
            seed = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise RuntimeError("SIGN_SEED must be 32-byte hex or unpadded base64url") from exc
    if len(seed) != 32:
        raise RuntimeError("SIGN_SEED must decode to exactly 32 bytes")
    return seed


class LocalSigner:
    def __init__(self, seed: bytes):
        self._key = Ed25519PrivateKey.from_private_bytes(seed)

    @property
    def did(self) -> str:
        from cryptography.hazmat.primitives import serialization

        public = self._key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return "did:key:z" + _b58encode(b"\xed\x01" + public)

    def sign(self, room: str, nonce: int, text: str) -> str:
        payload = f"{room}|{nonce}|{text}".encode("utf-8")
        return base64.urlsafe_b64encode(self._key.sign(payload)).rstrip(b"=").decode("ascii")


def next_nonce() -> int:
    global _last_nonce
    candidate = time.time_ns() // 1_000_000
    _last_nonce = max(candidate, _last_nonce + 1)
    return _last_nonce


def ensure_local_mode() -> None:
    if os.getenv("TASKS_MODE", "").lower() == "hosted" or os.getenv("RAILWAY_ENVIRONMENT"):
        raise RuntimeError("signing is disabled in hosted mode")


def post_signed(base_url: str, room: str, signer: LocalSigner, nonce: int, text: str) -> dict:
    signature = signer.sign(room, nonce, text)
    with httpx.Client(base_url=base_url, timeout=20, follow_redirects=False) as client:
        response = client.post(
            f"/r/{room}",
            json={"did": signer.did, "sig": signature, "nonce": str(nonce), "text": text},
        )
        if response.is_error:
            # Do not use raise_for_status(): its default message omits the server's
            # actionable text body. The request body/signature is deliberately not echoed.
            raise TechnocoreWriteError(
                response.status_code,
                response.reason_phrase,
                response.text,
            )
        return response.json()
