# Relay setup — single shared backend (Remy ↔ Cowork)

Remy and cowork (Claude Desktop) must use **one relay backend** so messages and tasks sent from either agent are visible to the other. This doc describes how to run the shared relay and point both Cursor (Remy) and Claude Desktop (cowork) at it.

---

## 1. Run the shared relay (one process, one DB)

Start a single relay server with a single database:

```bash
# From the remy repo root
make relay-run
```

This runs `relay_mcp/server.py` with `--db data/relay.db`. One process, one DB file.

**With Docker:**

```bash
make relay-up   # Starts remy + relay + ollama
```

The relay container uses `--db /app/data/relay.db` and mounts `./data:/app/data`, so the DB path on the host is `./data/relay.db` — the same as `make relay-run` when run from the repo.

**Verify:** `make relay-check` — checks that something is listening on `127.0.0.1:8765`.

---

## 2. Remy (Cursor) → shared backend

When working in the remy project in Cursor, the relay MCP config in `.cursor/mcp.json` already points at the **HTTP** endpoint, not stdio:

- **URL:** `http://127.0.0.1:8765/mcp`
- **Transport:** Cursor uses `mcp-proxy` with `streamablehttp` to that URL.

So Remy does **not** spawn a per-session stdio relay. It uses the same shared server. Ensure the shared relay is running (`make relay-run` or `make relay-up`) before relying on relay tools in Cursor.

Remy’s Python code (Telegram “Send to cowork”, briefings, relay tool executors) writes to the same DB: by default `data/relay.db` (i.e. `data_dir/relay.db`). If you run the relay server with a different DB path, set `RELAY_DB_PATH` in `.env` to that path so Remy’s client uses it too.

---

## 3. Cowork (Claude Desktop) → same backend

Point Claude Desktop at the **same** relay server (same URL, same DB behind it):

1. **Relay server** must be running (see above).

2. **Claude Desktop MCP config** (e.g. `~/Library/Application Support/Claude/claude_desktop_config.json`) should include:

   ```json
   "mcpServers": {
     "relay": {
       "command": "uvx",
       "args": [
         "mcp-proxy",
         "--transport",
         "streamablehttp",
         "http://127.0.0.1:8765/mcp"
       ]
     }
   }
   ```

3. **Agent names:** Use lowercase `remy` and `cowork` so both sides see the same inboxes and tasks.

4. **Restart Claude Desktop** after changing config.

---

## 4. End-to-end behaviour

- **Remy → cowork:** Remy posting via [Send to cowork] or `relay_post_message` writes to the shared DB; cowork’s `relay_get_messages` reads from it.
- **Cowork → Remy:** Cowork posting to Remy writes to the same DB; Remy’s relay tools and `/relay` (Telegram) read from it.

Both agents must use the same relay process (and thus the same `data/relay.db`). If either uses a different process or DB path, messages will not be delivered.

---

## 5. Optional: override relay DB path

If you run the relay server with a different DB path (e.g. a shared path outside the repo), set in `.env`:

```bash
RELAY_DB_PATH=/path/to/relay.db
```

Remy’s Python client will then use this path for all relay reads/writes so it stays in sync with that server.

---

## 6. Verification

1. Start the shared relay: `make relay-run` (or `make relay-up`).
2. **Remy → cowork:** In Cursor (remy project), use the relay tools to post a message to cowork (e.g. `relay_post_message` with `to_agent="cowork"`). In Claude Desktop (cowork), call `relay_get_messages(agent="cowork")` — the message should appear.
3. **Cowork → Remy:** In Claude Desktop, post a message to remy. In Cursor, call `relay_get_messages(agent="remy")` or use Telegram `/relay` — the message should appear.

You can also inspect the DB directly:

```bash
sqlite3 data/relay.db "SELECT id, from_agent, to_agent, substr(content,1,60) FROM messages ORDER BY created_at DESC LIMIT 5;"
```

---

## Summary

| Component        | Action |
|-----------------|--------|
| **Relay server** | One process: `make relay-run` or `make relay-up`; one DB: `data/relay.db` (or path set via relay’s `--db` and Remy’s `RELAY_DB_PATH`). |
| **Cursor (Remy)** | Already uses HTTP relay from `.cursor/mcp.json`; ensure relay is running. |
| **Claude Desktop (cowork)** | Add relay entry to MCP config pointing at `http://127.0.0.1:8765/mcp`; use agent names `remy` and `cowork`. |

See also: [US-relay-shared-backend](backlog/US-relay-shared-backend.md), [BUGS.md](../BUGS.md) (Bug 3, Bug 4).
