"""Signed tokens for secure file download links.

Used by the health server GET /files route and the get_file_download_link tool.
Token binds path + expiry; secret is FILE_LINK_SECRET or HEALTH_API_TOKEN.
"""

from __future__ import annotations

import base64
import hmac
import hashlib
import struct
import time


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(s: str) -> bytes | None:
    try:
        pad = 4 - (len(s) % 4)
        if pad != 4:
            s += "=" * pad
        return base64.urlsafe_b64decode(s)
    except Exception:
        return None


def encode_path_param(path: str) -> str:
    """Encode path for use in a URL query param (base64url)."""
    return _base64url_encode(path.encode("utf-8"))


def decode_path_param(encoded: str) -> str | None:
    """Decode path from URL query param. Returns None if invalid or empty."""
    raw = _base64url_decode(encoded)
    if raw is None or len(raw) == 0:
        return None
    try:
        s = raw.decode("utf-8")
        return s if s else None
    except Exception:
        return None


def create_token(path: str, expiry_ts: int, secret: str) -> str:
    """Build a signed token for path valid until expiry_ts (Unix timestamp)."""
    if not secret:
        return ""
    expiry_bytes = struct.pack(">Q", expiry_ts)
    payload = path.encode("utf-8") + expiry_bytes
    sig = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).digest()
    return _base64url_encode(expiry_bytes + sig)


def verify_token(path: str, token: str, secret: str) -> tuple[bool, str | None]:
    """
    Verify token for the given path and secret.

    Returns (True, None) if valid, or (False, reason) if invalid.
    """
    if not secret:
        return False, "File link secret not configured"
    if not token:
        return False, "Missing token"
    raw = _base64url_decode(token)
    if raw is None or len(raw) < 8 + 32:
        return False, "Invalid token format"
    expiry_ts = struct.unpack(">Q", raw[:8])[0]
    if time.time() > expiry_ts:
        return False, "Token expired"
    expiry_bytes = raw[:8]
    payload = path.encode("utf-8") + expiry_bytes
    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(expected, raw[8:40]):
        return False, "Invalid token"
    return True, None
