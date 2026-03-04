# User Story: Two-Way Claude Desktop ↔ Remy Relay

**Status:** ✅ Done

## Summary

As Dale, I want Remy (Telegram) to be able to receive messages from Claude Desktop and reply back through the same relay channel, so that Claude Desktop and Remy can work as true cowork peers rather than a one-directional dispatch pipe.

---

## Background

`CLAUDE.md` documents a relay MCP protocol that lets Claude Desktop send tasks and messages to Remy via `relay_post_message`, `relay_get_messages`, `relay_get_tasks`, etc. The relay is backed by an MCP server and is the established channel for agent-to-agent communication.

**The gap:** the relay is currently one-directional. Claude Desktop can push tasks and messages *to* Remy, but Remy (the Telegram bot) has no tools to:

1. Read its relay inbox (`relay_get_messages`, `relay_get_tasks`)
2. Post a reply back to cowork (`relay_post_message`, `relay_update_task`)

Remy's `ToolRegistry` has no relay tools. The only relay awareness lives in `CLAUDE.md`, which is a prompt for the Claude Desktop side.

The result: Dale has to manually relay Remy's output back into Claude Desktop by copy-pasting, defeating the purpose of the agent-to-agent channel.

**Related files:**
- `CLAUDE.md` — relay MCP spec (Claude Desktop side)
- `remy/ai/tools/` — ToolRegistry (Remy side, needs relay tools added)
- `remy/memory/database.py` — SQLite schema (relay inbox table goes here)
- `TODO.md` — PBI `US-claude-desktop-relay`

---

## Acceptance Criteria

1. **Remy can read its relay inbox.** Calling `relay_get_messages` from within a Remy conversation returns any pending messages sent by Claude Desktop (cowork).

2. **Remy can post a reply.** Calling `relay_post_message` from within a Remy conversation delivers a message to the cowork inbox that Claude Desktop can retrieve at its next session start.

3. **Remy can read and update tasks.** `relay_get_tasks` returns tasks assigned to `remy`; `relay_update_task` marks them in-progress, done, or needs-clarification.

4. **Full round-trip works end-to-end.** Claude Desktop → Remy → Claude Desktop without manual copy-paste.

5. **`/relay` inbox command works.** Dale can type `/relay` or "what's in my relay inbox?" in Telegram and Remy shows pending messages + tasks from cowork.

6. **No new public endpoint required.** Communication uses the existing relay MCP server (shared file or SQLite, same auth model as the Cloudflare tunnel). Remy talks to the relay as an MCP client, not via HTTP.

7. **Existing behaviour unchanged.** All existing Remy tools continue to work; the relay tools are additive.

8. **Authentication.** Relay calls use the shared secret already defined in `.env` for the MCP server. No new auth mechanism needed.

---

## Implementation

**Files to create:**
- `remy/ai/tools/relay.py` — `RelayToolExecutor` with handlers for all relay tool calls
- `docs/backlog/US-claude-desktop-relay.md` — this file

**Files to modify:**
- `remy/ai/tools/schemas.py` — add relay tool schemas to `TOOL_SCHEMAS`
- `remy/ai/tools/__init__.py` or `tool_registry.py` — register `RelayToolExecutor`
- `remy/bot/handlers.py` — add `/relay` slash command
- `SOUL.compact.md` — document relay commands under Capabilities

### Relay Tool Schemas

Add the following tools to `TOOL_SCHEMAS`:

```python
{
    "name": "relay_get_messages",
    "description": "Check Remy's relay inbox for messages from cowork (Claude Desktop). Call at the start of any cowork session or when Dale asks what's in the relay.",
    "input_schema": {
        "type": "object",
        "properties": {
            "unread_only": {
                "type": "boolean",
                "description": "If true, return only unread messages (default true)."
            }
        },
        "required": []
    }
},
{
    "name": "relay_post_message",
    "description": "Send a message from Remy to cowork (Claude Desktop) via the relay channel.",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The message content to send to cowork."
            },
            "thread_id": {
                "type": "string",
                "description": "Optional thread ID to reply in-thread."
            }
        },
        "required": ["content"]
    }
},
{
    "name": "relay_get_tasks",
    "description": "List tasks assigned to Remy from cowork. Use to find pending work.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "done", "needs_clarification", "all"],
                "description": "Filter tasks by status (default: pending)."
            }
        },
        "required": []
    }
},
{
    "name": "relay_update_task",
    "description": "Claim, complete, or flag a relay task from cowork.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "The task ID to update."},
            "status": {
                "type": "string",
                "enum": ["in_progress", "done", "needs_clarification"],
                "description": "New task status."
            },
            "result": {"type": "string", "description": "Result summary (for done)."},
            "notes": {"type": "string", "description": "Clarification notes (for needs_clarification)."}
        },
        "required": ["task_id", "status"]
    }
},
{
    "name": "relay_post_note",
    "description": "Post a shared observation or finding to the relay for cowork to read.",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags (e.g. ['gmail', 'audit'])."
            }
        },
        "required": ["content"]
    }
}
```

### RelayToolExecutor

`remy/ai/tools/relay.py` — thin wrapper that forwards calls to the relay MCP server.

The relay MCP server is already running (used by Claude Desktop). Remy connects as an MCP client using the same shared secret.

```python
# remy/ai/tools/relay.py

import os
import httpx  # or mcp client SDK — TBD based on what relay server exposes
from remy.utils.config import settings

RELAY_BASE_URL = settings.RELAY_MCP_URL          # e.g. http://localhost:7430
RELAY_SECRET   = settings.RELAY_MCP_SECRET
REMY_AGENT     = "remy"

class RelayToolExecutor:
    async def relay_get_messages(self, unread_only: bool = True) -> dict:
        ...

    async def relay_post_message(self, content: str, thread_id: str = None) -> dict:
        ...

    async def relay_get_tasks(self, status: str = "pending") -> dict:
        ...

    async def relay_update_task(self, task_id: str, status: str,
                                 result: str = None, notes: str = None) -> dict:
        ...

    async def relay_post_note(self, content: str, tags: list = None) -> dict:
        ...
```

> **Note:** The exact transport (HTTP REST, MCP stdio, or SQLite direct-read) depends on how the
> relay MCP server exposes its API. Audit `relay_mcp` server before implementing. If it's SQLite
> direct-access, `RelayToolExecutor` reads/writes the relay DB file directly with the shared secret
> as a row-level gate. If it's HTTP, use `httpx`. Prefer direct SQLite if available — no extra
> network hop.

### `/relay` Slash Command

Add to `bot/handlers.py`:

```python
async def _handle_relay_command(self, update, context):
    """Show pending relay inbox: messages + tasks from cowork."""
    # Calls relay_get_messages(unread_only=True) + relay_get_tasks(status="pending")
    # Formats as a Telegram message with counts and summaries
    # If empty: "Relay inbox is clear — nothing from cowork."
```

Natural language variants handled automatically via tool schemas ("check my relay inbox", "any messages from cowork?").

### SOUL.compact.md Update

Add to Capabilities line:
```
Relay (read/reply cowork inbox, task updates)
```

Add to Commands section:
```
/relay — show pending relay inbox from cowork
```

### Notes

- **Dependency:** Relay MCP server must be reachable from the Remy Docker container. If it's on the host, use `host.docker.internal` or Tailscale. Check before implementing.
- **Auth:** Use `RELAY_MCP_URL` and `RELAY_MCP_SECRET` env vars (add to `.env.example`).
- **No new DB table needed** unless we want a local relay cache. Prefer hitting the relay MCP server directly — single source of truth.
- **Morning briefing hook (optional):** Add a relay inbox check to `ProactiveScheduler._morning_briefing()` — if there are unread messages from cowork, include a one-liner: "📬 1 unread message from cowork."
- **Out of scope for this story:** Remy proactively *initiating* tasks to cowork (that's a different flow). This story is purely about read + reply.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Cowork sends a message; Dale asks "check relay" | Remy retrieves and displays the message |
| Remy replies to cowork | `relay_post_message` delivers to cowork inbox; Claude Desktop reads it at next session start |
| Cowork assigns a task; Remy claims it | `relay_update_task(status="in_progress")` succeeds; task shows as in_progress |
| Remy completes task | `relay_update_task(status="done", result="...")` succeeds; cowork sees completion |
| Relay inbox is empty | Remy reports "inbox clear" gracefully — no error |
| Relay MCP server unreachable | Graceful error: "Relay unavailable — check RELAY_MCP_URL config." No crash. |
| `/relay` slash command | Returns formatted inbox summary with counts of unread messages and pending tasks |
| All other Remy tools | Unchanged — relay tools are purely additive |

---

## Out of Scope

- Remy proactively sending unsolicited tasks *to* cowork (separate US)
- Remy acting as an MCP *server* (it's a client of the relay)
- New authentication mechanism (uses existing shared secret model)
- Local relay cache / SQLite inbox table in Remy's own DB (only if relay server is unreliable)
- Morning briefing relay check (optional nice-to-have — add as a follow-up task in this story if time permits)
