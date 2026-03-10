# Agent Tooling Setup — Cursor, Claude Desktop

This document describes how Remy's agent tooling is configured across Cursor and Claude Desktop.

---

## Overview

| Tool | Config location | Hooks |
|------|-----------------|-------|
| **Cursor** | `~/.cursor/mcp.json` (global) + `.cursor/mcp.json` (project) | `~/.cursor/hooks.json` (global) + `.cursor/hooks.json` (project) |
| **Claude Desktop** | `~/Library/Application Support/Claude/claude_desktop_config.json` | — |
| **Remy (Telegram bot)** | Docker | — |

Cursor merges global and project MCP configs. When you open Remy in Cursor, you get global tools (GitHub, filesystem, etc.) and any project-level MCP servers defined in `.cursor/mcp.json`.

---

## Hooks

### Global (`~/.cursor/hooks.json`)

| Hook | Script | Purpose |
|------|--------|---------|
| beforeShellExecution | `block-dangerous-commands.sh` | Block `rm -rf`, `DROP TABLE`, `TRUNCATE`, `format`, `mkfs`, `dd` |
| afterShellExecution | `audit-shell.sh` | Append shell commands to `~/.cursor/hooks/audit.log` |
| sessionEnd | `audit-session-end.sh` | Log session end (reason, duration) to audit log |
| stop | `notify-complete.sh` | Play sound when agent completes. Disable: `CURSOR_NOTIFY_COMPLETE=0` |

### Project (`.cursor/hooks.json`)

| Hook | Script | Purpose |
|------|--------|---------|
| sessionStart | `session-reminder.sh` | Inject relay check-in reminder (reinforces CLAUDE.md) |
| beforeReadFile | `protect-sensitive-files.sh` | Block reading `.env`, `data/*.db`, credentials, `*.pem`, `*.key` |
| afterFileEdit | `format-after-edit.sh` | Run `ruff format` (or `black`) on Python files |
| afterMCPExecution | `audit-mcp.sh` | Log relay tool usage to `.cursor/audit.log` |
| subagentStop | `audit-subagent.sh` | Log subagent completion to `.cursor/audit.log` |

### Audit logs

- **Global:** `~/.cursor/hooks/audit.log` (or `$CURSOR_AUDIT_LOG`)
- **Project:** `.cursor/audit.log` (gitignored)

---

## Skills

Skills are loaded from:

- **Claude Code:** `.claude/skills/`
- **Cursor:** `.cursor/skills/`

Keep them in sync. Current skills:

| Skill | Description |
|-------|-------------|
| `next-pbi` | Recommends next PBI from TODO.md, BUGS.md, docs/backlog/ |
| `SHIP-IT` | Full deployment pipeline: docs, Docker restart, tests, commit & push |

---

## Best Practices Applied

1. **MCP:** Project-level relay in `.cursor/mcp.json` so Cursor gets relay tools when working on Remy.
2. **Hooks:** Safety (block destructive commands), file protection (secrets/DB), auto-format after edit.
3. **Skills:** Gerund naming, clear descriptions, `name` + `description` in frontmatter.
4. **CLAUDE.md:** Concise relay guide; session-start checklist for `relay_get_messages` and `relay_get_tasks`.

---

## Restart After Config Changes

- **Cursor:** Restart Cursor to load new MCP servers and hooks.
- **Claude Desktop:** Fully quit and reopen after editing `claude_desktop_config.json`.
