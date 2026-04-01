"""HMAC-signed cookie sessions for A-Eye authentication.

No external dependencies — uses Python stdlib only.
Signing key is derived from the password, so changing the password
automatically invalidates all existing sessions.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

SESSION_TTL = 30 * 24 * 3600  # 30 days in seconds
COOKIE_NAME = "aeye_session"


def _derive_key(password: str) -> bytes:
    """Derive a signing key from the password via SHA-256."""
    return hashlib.sha256(password.encode("utf-8")).digest()


def create_session(username: str, password: str) -> str:
    """Create a signed session cookie value.

    Returns a base64-encoded string: payload.signature
    """
    key = _derive_key(password)
    payload = json.dumps({
        "user": username,
        "exp": int(time.time()) + SESSION_TTL,
    }).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload).decode("ascii")
    sig = hmac.new(key, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_session(cookie_value: str, username: str, password: str) -> bool:
    """Verify a signed session cookie.

    Returns True only if the signature is valid, the user matches,
    and the session hasn't expired.
    """
    try:
        parts = cookie_value.split(".", 1)
        if len(parts) != 2:
            return False
        payload_b64, sig = parts

        key = _derive_key(password)
        expected_sig = hmac.new(key, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(sig, expected_sig):
            return False

        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if payload.get("user") != username:
            return False
        if payload.get("exp", 0) < time.time():
            return False

        return True
    except Exception:
        return False
