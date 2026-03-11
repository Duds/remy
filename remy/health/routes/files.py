"""File streaming endpoint."""

from __future__ import annotations

from typing import cast

from ..utils import check_token


async def handle_files(request) -> "aiohttp.web.Response":
    """Stream a file from allowed base dirs. Requires path= and token= (signed)."""
    import os

    from aiohttp import web  # type: ignore[import]

    from ...ai.input_validator import sanitize_file_path
    from ...config import settings
    from ...file_link import decode_path_param, verify_token

    path_encoded = request.rel_url.query.get("path", "").strip()
    token = request.rel_url.query.get("token", "").strip()
    if not path_encoded or not token:
        return web.json_response(
            {"error": "Missing path or token query parameter"},
            status=400,
        )

    path = decode_path_param(path_encoded)
    if path is None:
        return web.json_response({"error": "Invalid path parameter"}, status=400)

    secret = (
        os.environ.get("FILE_LINK_SECRET") or os.environ.get("HEALTH_API_TOKEN") or ""
    ).strip()
    ok, reason = verify_token(path, token, secret)
    if not ok:
        return web.json_response(
            {"error": reason or "Unauthorized"},
            status=401,
        )

    safe_path, err = sanitize_file_path(path, settings.allowed_base_dirs)
    if err or safe_path is None:
        return web.json_response({"error": err or "Access denied"}, status=403)

    file_path = __import__("pathlib").Path(safe_path)
    if not file_path.exists():
        return web.json_response({"error": "File not found"}, status=404)
    if not file_path.is_file():
        return web.json_response({"error": "Not a file"}, status=400)

    chunk_size = 65536
    try:
        import mimetypes

        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"
        disposition = f'attachment; filename="{file_path.name}"'
    except Exception:
        content_type = "application/octet-stream"
        disposition = f'attachment; filename="{file_path.name}"'

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": content_type,
            "Content-Disposition": disposition,
        },
    )
    await response.prepare(request)
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            await response.write(chunk)
    await response.write_eof()
    return cast(web.Response, response)
