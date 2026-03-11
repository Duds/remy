"""Commands endpoint (ship-it)."""

from __future__ import annotations

import asyncio
import os

from ..utils import check_token


async def handle_ship_it(request: "aiohttp.web.Request") -> "aiohttp.web.Response":
    """Run the SHIP-IT pipeline: git fetch, diff against main, run tests."""
    from aiohttp import web  # type: ignore[import]

    if request.method != "POST":
        return web.json_response(
            {"error": "Method not allowed — use POST"},
            status=405,
        )
    if not check_token(request):
        return web.json_response(
            {"error": "Unauthorized — set Authorization: Bearer <HEALTH_API_TOKEN>"},
            status=401,
        )

    workspace = os.environ.get("WORKSPACE_ROOT", "").strip()
    if not workspace:
        return web.json_response(
            {"error": "WORKSPACE_ROOT not set — cannot run SHIP-IT"},
            status=503,
        )
    workspace_path = __import__("pathlib").Path(workspace)
    if not workspace_path.is_dir():
        return web.json_response(
            {"error": f"WORKSPACE_ROOT is not a directory: {workspace}"},
            status=503,
        )

    dry_run = False
    try:
        if request.content_length and request.content_length > 0:
            body = await request.json()
            dry_run = bool(body.get("dry_run", False))
    except Exception:
        pass

    result: dict = {
        "branch": None,
        "diff_summary": None,
        "tests_passed": None,
        "tests_output": None,
        "error": None,
    }

    async def _run(cmd: list[str], cwd: str) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        return proc.returncode or 0, (stdout or b"").decode("utf-8", errors="replace")

    code, out = await _run(["git", "fetch", "origin", "main"], str(workspace_path))
    if code != 0:
        result["error"] = f"git fetch failed: {out[:500]}"
        return web.json_response(result, status=200)

    code, out = await _run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], str(workspace_path)
    )
    result["branch"] = out.strip() if code == 0 else None

    code, out = await _run(
        ["git", "diff", "origin/main...HEAD", "--stat"],
        str(workspace_path),
    )
    result["diff_summary"] = out.strip() if code == 0 else None

    if dry_run:
        result["tests_passed"] = None
        result["tests_output"] = "(dry run — tests skipped)"
        return web.json_response(result)

    code, out = await _run(
        ["python3", "-m", "pytest", "tests/", "-v", "--tb=short"],
        str(workspace_path),
    )
    result["tests_passed"] = code == 0
    result["tests_output"] = out[-4000:] if len(out) > 4000 else out

    return web.json_response(result)
