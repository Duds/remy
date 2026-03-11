"""Shared utilities for health server routes."""

from __future__ import annotations

import os
import time

from remy.exceptions import (
    RemyError,
    ServiceUnavailableError,
    StorageError,
    ToolExecutionError,
    ValidationError,
)

_START_TIME = time.monotonic()


def remy_error_to_http(e: RemyError) -> tuple[dict, int]:
    """Map RemyError subclasses to JSON body and HTTP status code."""
    if isinstance(e, ValidationError):
        return ({"error": str(e)}, 400)
    if isinstance(e, (ServiceUnavailableError, StorageError)):
        return ({"error": str(e)}, 503)
    if isinstance(e, ToolExecutionError):
        return ({"error": str(e)}, 500)
    return ({"error": "Internal error"}, 500)


def get_start_time() -> float:
    """Return monotonic start time for uptime calculation."""
    return _START_TIME


def check_token(request) -> bool:
    """
    Return True if the request passes token auth.

    If HEALTH_API_TOKEN is not set (or empty), all requests pass.
    Otherwise, the token must be supplied via:
      - Authorization: Bearer <token>  header, or
      - ?token=<token>                 query param
    """
    token = os.environ.get("HEALTH_API_TOKEN", "").strip()
    if not token:
        return True
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:] == token:
        return True
    if request.rel_url.query.get("token") == token:
        return True
    return False
