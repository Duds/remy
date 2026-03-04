"""Tests for remy/file_link.py — signed file download tokens."""

import time

from remy.file_link import (
    create_token,
    verify_token,
    encode_path_param,
    decode_path_param,
)


def test_encode_decode_path_param():
    """Path param round-trips."""
    path = "/Users/dale/Documents/notes.md"
    encoded = encode_path_param(path)
    assert isinstance(encoded, str)
    assert "=" not in encoded
    decoded = decode_path_param(encoded)
    assert decoded == path


def test_decode_path_param_invalid():
    """Invalid base64 returns None."""
    assert decode_path_param("!!!") is None
    assert decode_path_param("") is None


def test_create_token_empty_secret():
    """Empty secret yields empty token."""
    assert create_token("/tmp/foo", int(time.time()) + 900, "") == ""


def test_create_and_verify_token():
    """Valid token verifies for the same path and secret."""
    path = "/Users/dale/Documents/notes.md"
    secret = "test-secret"
    expiry_ts = int(time.time()) + 900
    token = create_token(path, expiry_ts, secret)
    assert token
    ok, reason = verify_token(path, token, secret)
    assert ok is True
    assert reason is None


def test_verify_token_wrong_path():
    """Token for one path fails for another."""
    path = "/Users/dale/Documents/notes.md"
    secret = "test-secret"
    expiry_ts = int(time.time()) + 900
    token = create_token(path, expiry_ts, secret)
    ok, reason = verify_token("/Users/dale/other.txt", token, secret)
    assert ok is False
    assert "Invalid" in (reason or "")


def test_verify_token_expired():
    """Expired token fails."""
    path = "/tmp/foo"
    secret = "test-secret"
    expiry_ts = int(time.time()) - 60
    token = create_token(path, expiry_ts, secret)
    ok, reason = verify_token(path, token, secret)
    assert ok is False
    assert "expired" in (reason or "").lower()


def test_verify_token_empty_secret():
    """Verification with empty secret fails."""
    ok, reason = verify_token("/tmp/foo", "sometoken", "")
    assert ok is False
    assert "secret" in (reason or "").lower()


def test_verify_token_invalid_format():
    """Malformed token fails."""
    ok, reason = verify_token("/tmp/foo", "tooshort", "secret")
    assert ok is False
