# User Story: Terminal UI for Remy

**Status:** ✅ Done

## Summary
As a developer or user, I want to run Remy in a terminal and chat via a local TUI so that I can use Remy without Telegram for local development, debugging, or preference.

---

## Background

Remy today is Telegram-only ([remy/main.py](../../remy/main.py)); the only other CLI is `remy.cli.qmd` for memory search. A TUI provides an alternative front-end reusing the same pipeline (Claude, tools, SOUL, memory, conversation store) so behaviour is identical and no duplicate logic.

---

## Acceptance Criteria

1. **Entry point.** A command (e.g. `python -m remy.tui` or `make tui`) starts an interactive TUI; same `.env` and `data_dir` as the main app.
2. **Chat.** User can type a message and send; Remy responds using the same `stream_with_tools` path, with streamed text and tool-use status visible in the TUI.
3. **History.** Conversation is persisted via existing `ConversationStore`; TUI uses a dedicated session (user_id=0, session key `user_0_YYYYMMDD`) so TUI and Telegram sessions stay separate.
4. **System prompt & memory.** SOUL and memory injector are used as in the Telegram path (same `settings.soul_md`, `MemoryInjector.build_system_prompt` for the TUI user).
5. **Cancel.** User can cancel an in-flight request (Ctrl+C) via `SessionManager.request_cancel`.
6. **Graceful exit.** Ctrl+Q exits without breaking the pipeline; no Telegram or health server started when running TUI.

---

## Implementation

**Files:** `remy/tui/__init__.py`, `remy/tui/__main__.py`, `remy/tui/screen.py`, `remy/tui/runner.py`, `requirements.txt`, `Makefile`, `README.md`.

- **Package:** `remy/tui/` with `__main__.py` as entry; `screen.py` for the Textual app and chat layout; `runner.py` builds deps and runs one chat turn (stream_with_tools + persist).
- **Shared usage:** Instantiate `DatabaseManager`, `ConversationStore`, `SessionManager`, `ClaudeClient`, `ToolRegistry`, `MemoryInjector`, and other deps from existing modules (same as `main.py` up to the point where the Telegram bot is built). Do not start `TelegramBot` or health server.
- **TUI flow:** On send: load `get_recent_turns` for TUI session key, build messages and system prompt (same logic as chat handler), call `claude_client.stream_with_tools(...)`; in the async for loop, handle `TextChunk` (append to reply widget), `ToolStatusChunk` (show "Using …"), `ToolTurnComplete` (optionally show compact tool summary); persist user turn and assistant turn via `conv_store.append_turn`.
- **Session key:** Constant `TUI_USER_ID = 0` and `SessionManager.get_session_key(TUI_USER_ID, None)` so session key is `user_0_YYYYMMDD`.
- **Dependency:** `textual>=0.47` in `requirements.txt`.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| Launch TUI, send a message, receive streamed reply | History persists and next message has context |
| Request that triggers a tool (e.g. time) | TUI shows tool status and final reply |
| Start long-running request, trigger Ctrl+C | Stream stops and UI is usable again |
| Quit with Ctrl+Q | Exit cleanly; no Telegram or health server processes left |
| Run `make tui` or `python -m remy.tui` | TUI starts using same `.env` and data dir |

---

## Out of Scope

- Voice, photo, document input in TUI.
- HTTP API for remote TUI clients.
- Running TUI inside Docker as primary deployment.
- Sharing the same conversation with Telegram (TUI has its own session).
