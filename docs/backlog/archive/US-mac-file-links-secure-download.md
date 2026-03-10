# User Story: Mac File Links and Secure Download via Tunnel

**Status:** ✅ Done

## Summary

As Dale, I want Remy to link to specific files or directories on my Mac when referring to a doc or file in chat, and to let me download that file securely from Telegram even when I'm not on the same network (e.g. on mobile data or work Wi‑Fi), so that I can open or save the file without remoting into the Mac.

---

## Background

When Remy answers questions like "your fence notes are in ~/Documents/Home/fence-notes.md" or "I found the quote in that file", the path is only useful if Dale is at the Mac. From Telegram on a phone or another network, there is no way to open that path or fetch the file.

Remy already has:
- **Allowed file access**: `read_file` and the file indexer use `sanitize_file_path()` with `allowed_base_dirs` (e.g. ~/Projects, ~/Documents) and a denylist (`.env`, `.ssh/`, `.git/`, etc.).
- **Secure tunnel**: Cloudflare Tunnel exposes the health server at `https://remy.dalerogers.com.au` with Bearer-token protection for `/logs` and `/telemetry` (see US-cloudflare-tunnel-remote-observability).

The gap is: **no way to turn “this file” into something Dale can open or download from Telegram when off the home network.**

---

## Brainstorming — How to do this

### Option A: Send file as Telegram document

- Remy uses the Telegram Bot API `sendDocument(chat_id, document=file_path)` to send the file into the conversation.
- **Pros:** Works from any network; no extra endpoint; file appears in chat.
- **Cons:** Telegram bot file size limit (50 MB); can clutter chat; not a “link” to the path.

### Option B: One-time download link via existing tunnel

- Add a protected route on the health server (e.g. `GET /files?path=...&token=...`) that streams the file. Remy generates a short-lived signed URL (e.g. `https://remy.dalerogers.com.au/files?path=...&token=...`) and sends it in the message.
- **Pros:** Works for larger files; single link to tap; reuses existing Cloudflare Tunnel (HTTPS + auth); no file stored on Telegram.
- **Cons:** Requires tunnel to be running; token in URL (mitigated by short expiry and HMAC).

### Option C: Hybrid (recommended)

- **Small / typical docs:** Offer both — Remy can send the file into the chat (Option A) and/or include a download link (Option B) so Dale can open in browser or save.
- **Larger files:** Only link (Option B); optionally mention “File is large; use the link to download.”
- **Security:** Same path allowlist/denylist as `read_file`; no directory listing; signed token for links (path + expiry + secret); Bearer token alternative for `/files` consistent with `/logs` and `/telemetry`.

### Tunnelling and “not on same network”

- **Tunnelling is already in place:** The Cloudflare Tunnel (US-cloudflare-tunnel-remote-observability) makes the Mac’s health server reachable at `https://remy.dalerogers.com.au`. No new tunnel is required.
- **Secure download** means: (1) HTTPS only, (2) auth via signed token or Bearer, (3) only paths under allowed bases and not in the denylist, (4) short-lived tokens (e.g. 5–15 minutes).

### Tool shape

- New tool(s) Remy can call when referring to a file, e.g.:
  - `get_file_download_link(path, expires_in_minutes=15)` → returns a signed URL and optionally a short message to send (“Download: …”).
  - `send_file_to_user(path)` → sends the file as a Telegram document (for small files), or returns “File too large; use the link instead” with a link.
- Or a single tool: `share_file_with_user(path, method="link"|"send"|"both")` that does the right thing and returns the text/link to include in the reply.

**Implemented (download-link only):** GET /files route with signed tokens, `get_file_download_link` tool, `remy/file_link.py` for create/verify token. Config: `FILE_LINK_BASE_URL`, `FILE_LINK_EXPIRY_MINUTES`, `FILE_LINK_SECRET` (optional; falls back to `HEALTH_API_TOKEN`). See `.env.example`. Option A (send file via Telegram) is out of scope for this implementation.

### Out of scope for this US

- Directory listing or “browse my Mac” from Telegram.
- Editing files via the link (read-only / download only).
- Serving files from outside the existing allowed bases.

---

## Acceptance Criteria

1. **Remy can generate a secure download link for an allowed file.** When Remy refers to a file under `allowed_base_dirs` (e.g. ~/Projects, ~/Documents), it can call a tool that returns a short-lived signed URL (e.g. 15-minute expiry) pointing at the health server’s file-serving route. The link works when the Cloudflare Tunnel is up (e.g. `https://remy.dalerogers.com.au/...`).

2. **File-serving route is protected.** A new route (e.g. `GET /files`) accepts a signed token (and optionally path) in the query string. It validates the signature (path + expiry + secret), checks the path with `sanitize_file_path()`, then streams the file with an appropriate `Content-Type` and `Content-Disposition`. Requests without a valid token return 401.

3. **Remy can send small files as Telegram documents.** For files under a size limit (e.g. 10 MB to stay under Telegram’s 50 MB and avoid timeouts), Remy can send the file directly into the chat via the bot so the user can open/save it without leaving Telegram.

4. **Same security as read_file.** Only paths allowed by `sanitize_file_path()` (same allowlist and denylist as `read_file`) are linkable or sendable. Denied names/directories (e.g. `.env`, `.git`, `.ssh`) are never accessible.

5. **Works off the home network.** Using the existing tunnel, the download link is reachable from any network (mobile, work, etc.) as long as the tunnel is running. Sending the file via Telegram works from any network without depending on the tunnel.

6. **Clear UX when referring to a file.** When Remy’s reply references a specific file, it can include either “I’ve attached the file” (if sent), “Download: [link]” (if link only), or both, and no sensitive paths or tokens are logged in plain text.

7. **No directory listing.** The `/files` endpoint only serves a single file per request; no listing of directories or multiple paths.

---

## Implementation

**Files:**

- `remy/health.py` — add `GET /files?path=...&token=...` (or `token` encoding path+expiry); validate signature; use `sanitize_file_path()`; stream file; set `Content-Disposition: attachment; filename="..."`.
- `remy/ai/input_validator.py` or a small `remy/health/file_token.py` — sign/verify token (e.g. HMAC-SHA256 of path + expiry, secret from `HEALTH_API_TOKEN` or a dedicated `FILE_LINK_SECRET`).
- `remy/ai/tool_registry.py` + tool executor — new tool(s) e.g. `get_file_download_link(path, expires_in_minutes=15)` and/or `send_file_to_user(path)` (calls bot `sendDocument`; path sanitized).
- `remy/bot/streaming.py` or tool result handling — when a tool returns a “share file” result, include the link and/or confirm “file sent” in the reply.
- `remy/config.py` — optional `FILE_LINK_EXPIRY_MINUTES`, `FILE_SEND_MAX_BYTES` (e.g. 10 * 1024 * 1024).
- `.env.example` — document `FILE_LINK_SECRET` (optional; fallback to `HEALTH_API_TOKEN` for signing).

**Token design (sketch):**

```python
# Generate: token = base64url(expiry_ts | hmac(path + expiry_ts))
# Verify: decode, check expiry_ts > now(), recompute hmac, constant-time compare
# URL: /files?path=<base64url(path)>&token=<token>
```

**Streaming (sketch):**

- Resolve path with `sanitize_file_path()`; if error, return 403.
- Open file in binary mode; stream in chunks (e.g. 64 KB); set `Content-Type` from mimetypes or default `application/octet-stream`; set `Content-Disposition: attachment; filename="basename"`.

**Notes:**

- Depends on Cloudflare Tunnel being configured (US-cloudflare-tunnel-remote-observability). If tunnel is not up, the link will not work from outside the home network; Remy can still send small files via Telegram.
- Large files: only offer link; do not send via Telegram if over `FILE_SEND_MAX_BYTES`.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Remy calls tool with path under ~/Documents | Signed URL returned; GET /files with token streams file; 200 |
| GET /files without token or invalid token | 401 |
| GET /files with expired token | 401 |
| GET /files with path outside allowed_base_dirs | 403 after sanitize_file_path |
| GET /files with path containing .. or denylist segment | 403 |
| Send file via Telegram (file &lt; 10 MB) | Document appears in chat |
| Send file via Telegram (file &gt; 10 MB) | Remy replies with download link only, no send |
| User on different network opens link (tunnel up) | File downloads over HTTPS |
| No directory listing | GET /files with no path or path=a_directory returns 400 or 403 |

---

## Out of Scope

- Directory listing or browsing the filesystem from Telegram.
- Editing or uploading files via this mechanism (read-only / download).
- New tunnel product; re-use existing Cloudflare Tunnel only.
- Serving files from paths outside the existing `read_file` allowlist/denylist.
- Public, unauthenticated file URLs (all access is token- or Bearer-protected).
