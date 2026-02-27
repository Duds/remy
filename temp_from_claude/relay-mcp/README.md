# relay_mcp — Inter-agent communication for Claude agents

A lightweight local MCP server that lets two Claude agents (e.g. **cowork** and **remy**) exchange messages, delegate tasks, and share notes — across sessions and without being in the same conversation.

```
[Cowork / Dale's Cowork session]          [Remy / Claude Code agent]
          │                                         │
          │  relay_post_task(to="remy", ...)        │
          │  relay_post_message(to="remy", ...)     │
          ▼                                         │
    ┌───────────────────┐                           │
    │    relay_mcp      │ ◄─────────────────────────┘
    │  (HTTP on :8765)  │   relay_get_tasks(agent="remy")
    │  SQLite backend   │   relay_update_task(id, status="done", result=...)
    └───────────────────┘
          ▲
          │  relay_get_task_status(task_id)
          │  relay_get_notes()
          │
[Cowork / Dale's Cowork session]
```

---

## Setup

### 1. Install dependencies

```bash
cd relay-mcp
pip install -r requirements.txt
```

### 2. Start the server

```bash
python server.py
# Listening on http://127.0.0.1:8765
```

Keep it running in the background. Use a screen/tmux session or a launchd/systemd service for persistence.

Custom port or DB location:
```bash
python server.py --port 9000 --db ~/Library/Application\ Support/relay-mcp/relay.db
```

### 3. Add to both agents' MCP config

**For Cowork** — add to `~/.claude/settings.json` (or your Cowork MCP config):

```json
{
  "mcpServers": {
    "relay": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

**For Remy (Claude Code)** — add to `~/.claude.json` or the project's `.mcp.json`:

```json
{
  "mcpServers": {
    "relay": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

### 4. Give Remy her CLAUDE.md

Copy `CLAUDE_remy.md` into Remy's working directory as `CLAUDE.md` (or append it to an existing one). This tells her how to use the relay at the start of each session.

---

## How it works

### Messages
Point-to-point, like a simple inbox. One agent posts, the other reads.

```python
# Cowork delegates
relay_post_message(from_agent="cowork", to_agent="remy",
                   content="Please label all Radford Nexus emails as 4-Personal & Family")

# Remy checks inbox at session start
relay_get_messages(agent="remy")
```

### Tasks
Structured work items with status tracking. Better than messages for things that need a result.

```python
# Cowork posts a task
relay_post_task(
    from_agent="cowork", to_agent="remy",
    task_type="gmail_label",
    description="Label all unlabelled Radford Nexus Digest emails as 4-Personal & Family",
    params={"query": "from:nexus@radford.act.edu.au -has:userlabels after:2025/02/27",
            "label": "4-Personal & Family"}
)

# Remy claims it
relay_update_task(task_id="abc123", status="in_progress")

# Remy completes it
relay_update_task(task_id="abc123", status="done",
                  result="Applied label to 31 emails.")

# Cowork checks
relay_get_task_status(task_id="abc123")
```

### Shared notes
Broadcast observations both agents can read. Good for audit findings, summaries, and context that persists.

```python
relay_post_note(from_agent="remy", content="Gmail quick wins complete — 312 trashed, 87 labelled.",
                tags=["gmail", "complete"])

relay_get_notes(tags=["gmail"])
```

---

## Task statuses

| Status | Meaning |
|---|---|
| `pending` | Posted, not yet claimed |
| `in_progress` | Remy has claimed it and is working |
| `done` | Completed successfully |
| `failed` | Could not complete — see `result` and `notes` |
| `needs_clarification` | Remy is blocked and needs input from cowork |

---

## File layout

```
relay-mcp/
├── server.py          ← The MCP server (run this)
├── requirements.txt
├── README.md          ← This file
├── CLAUDE_remy.md     ← Copy to Remy's CLAUDE.md
└── relay.db           ← Created automatically on first run
```

---

## Security note

The server binds to `127.0.0.1` by default — local only. Do not expose it to the network unless you add authentication.
