"""Enkel sessionsautentisering med delat lösenord (cookie)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request

SESSION_COOKIE = "karriar_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 dagar


def _session_secret() -> bytes:
    raw = os.getenv("KARRIAR_SESSION_SECRET", "").strip()
    if not raw:
        pw = os.getenv("KARRIAR_PASSWORD", "").strip()
        if pw:
            return hashlib.sha256(f"karriar-session:{pw}".encode()).digest()
        raise RuntimeError(
            "Sätt KARRIAR_SESSION_SECRET eller KARRIAR_PASSWORD i miljön."
        )
    return raw.encode() if isinstance(raw, str) else raw


def get_password() -> str:
    pw = os.getenv("KARRIAR_PASSWORD", "").strip()
    if not pw:
        raise RuntimeError(
            "KARRIAR_PASSWORD måste sättas (t.ex. i .env eller docker-compose)."
        )
    return pw


def verify_password(candidate: str) -> bool:
    expected = get_password()
    return secrets.compare_digest(candidate, expected)


def create_session_token() -> str:
    issued = int(time.time())
    payload = str(issued).encode()
    sig = hmac.new(_session_secret(), payload, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(payload + b"." + sig).decode().rstrip("=")
    return token


def verify_session_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode())
        issued_b, sig = raw.split(b".", 1)
        issued = int(issued_b.decode())
        expected = hmac.new(_session_secret(), issued_b, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return False
        if time.time() - issued > SESSION_MAX_AGE:
            return False
        return True
    except (ValueError, OSError):
        return False


def is_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    return verify_session_token(token)


def cookie_secure() -> bool:
    return os.getenv("KARRIAR_COOKIE_SECURE", "false").lower() in (
        "1",
        "true",
        "yes",
    )
