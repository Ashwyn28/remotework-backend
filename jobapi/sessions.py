"""Signed session tokens, kept in an HttpOnly cookie.

The token says who is signed in and when; an HMAC stops anyone from editing it. It also
carries the account's session version, so deleting an account (or a future "sign out
everywhere") invalidates every copy at once.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

MAX_AGE = 30 * 24 * 3600  # thirty days


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, payload: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def issue(secret: str, sub: str, version: int, now: float | None = None) -> str:
    payload = _b64(json.dumps({"sub": sub, "v": version, "iat": int(now or time.time())}).encode())
    return f"{payload}.{_sign(secret, payload)}"


def read(secret: str, token: str | None, now: float | None = None) -> tuple[str, int] | None:
    """(sub, session version) for a genuine, unexpired token; None otherwise."""
    if not token or token.count(".") != 1 or len(token) > 1024:
        return None
    payload, signature = token.split(".")
    if not hmac.compare_digest(_sign(secret, payload), signature):
        return None
    try:
        data = json.loads(_unb64(payload))
        sub, version, issued = str(data["sub"]), int(data["v"]), int(data["iat"])
    except (ValueError, KeyError, TypeError):
        return None
    if (now or time.time()) - issued > MAX_AGE:
        return None
    return sub, version
