"""Tests for remy.ai.tools.run_python — sandboxed Python execution (Phase A)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from remy.ai.tools.run_python import (
    MAX_OUTPUT_BYTES,
    TIMEOUT_SECONDS,
    exec_run_python,
    run_python,
)

USER_ID = 42


def make_registry():
    """Mock registry (run_python does not use registry deps)."""
    return MagicMock()


# --- run_python (sync) ---


def test_run_python_simple_print():
    """Simple expression: print(2**32) returns 4294967296."""
    result = run_python("print(2 ** 32)")
    assert "4294967296" in result


def test_run_python_compound_interest():
    """Calculation example: compound interest."""
    code = """
principal = 5000
rate = 0.07
years = 10
result = principal * (1 + rate) ** years
print(round(result, 2))
"""
    result = run_python(code)
    assert "9835.76" in result


def test_run_python_stderr_traceback():
    """Script that raises ZeroDivisionError includes traceback in output."""
    result = run_python("1 / 0")
    assert "ZeroDivisionError" in result
    assert "division by zero" in result


def test_run_python_blocked_import_subprocess():
    """Importing subprocess raises PermissionError in sandbox."""
    result = run_python("import subprocess")
    assert "PermissionError" in result
    assert "subprocess" in result.lower()


def test_run_python_blocked_import_shutil():
    """Importing shutil raises PermissionError in sandbox."""
    result = run_python("import shutil")
    assert "PermissionError" in result
    assert "shutil" in result.lower()


def test_run_python_output_truncated():
    """Output larger than MAX_OUTPUT_BYTES is truncated with a note."""
    n = MAX_OUTPUT_BYTES + 100
    code = f"print('x' * {n})"
    result = run_python(code)
    assert len(result) <= len(str(MAX_OUTPUT_BYTES)) + 200 + MAX_OUTPUT_BYTES
    assert "truncated" in result.lower()
    assert str(MAX_OUTPUT_BYTES) in result


def test_run_python_no_output():
    """Script with no print returns (no output)."""
    result = run_python("x = 1 + 1")
    assert "(no output)" in result


def test_run_python_timeout():
    """Script that runs longer than TIMEOUT_SECONDS is killed; timeout message returned."""
    result = run_python("while True: pass")
    assert "[Timeout]" in result
    assert str(TIMEOUT_SECONDS) in result


def test_run_python_isolated_tmpdir():
    """Each run uses a fresh temp dir; script can write a file but it does not persist."""
    code = """
with open('written.txt', 'w') as f:
    f.write('hello')
print('ok')
"""
    result = run_python(code)
    assert "ok" in result
    # Run again to ensure no state leaks (e.g. written.txt from previous run)
    result2 = run_python("import os; print(len(os.listdir('.')))")
    assert "1" in result2 or "0" in result2  # only script.py or empty in fresh dir


# --- exec_run_python (async, tool executor) ---


@pytest.mark.asyncio
async def test_exec_run_python_success():
    """Executor runs code and returns stdout."""
    registry = make_registry()
    result = await exec_run_python(registry, {"code": "print(2 + 2)"}, USER_ID)
    assert "4" in result


@pytest.mark.asyncio
async def test_exec_run_python_empty_code():
    """Executor returns message when code is missing or empty."""
    registry = make_registry()
    result = await exec_run_python(registry, {}, USER_ID)
    assert "no code" in result.lower() or "provide" in result.lower()

    result2 = await exec_run_python(registry, {"code": "   \n  "}, USER_ID)
    assert "no code" in result2.lower() or "provide" in result2.lower()
