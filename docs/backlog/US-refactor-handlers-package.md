# User Story: Refactor handlers.py into Package

**Status:** ⬜ Backlog

**Priority:** P1

## Summary

As a developer, I want to split `remy/bot/handlers.py` (3,400+ lines) into a modular package structure so that the codebase is easier to navigate, test, and maintain.

---

## Background

The `handlers.py` file has grown to over 3,400 lines containing 50+ command handlers, message processing logic, streaming utilities, and authentication checks. This monolithic structure makes it difficult to:

- Find specific handlers quickly
- Test handlers in isolation
- Understand the scope of changes
- Onboard new contributors

The March 2026 engineering review identified this as a P2 refactoring priority. The file currently contains:

- **Core utilities**: `MessageRotator`, `_build_message_from_turn`, `_trim_messages_to_budget`, auth checks
- **File handlers**: `/read`, `/write`, `/ls`, `/find`, `/set_project`, `/scan_downloads`, `/organize`, `/clean`
- **Email handlers**: `/gmail-*` commands (unread, search, read, labels, classify)
- **Calendar handlers**: `/calendar`, `/calendar-today`, `/schedule`
- **Memory handlers**: `/goals`, `/plans`, `/consolidate`, `/compact`
- **Chat processing**: Main message handler with streaming, tool use, and conversation persistence
- **Admin handlers**: `/diagnostics`, `/stats`, `/logs`, `/costs`

---

## Acceptance Criteria

1. **Package structure created.** `remy/bot/handlers/` directory with `__init__.py` that re-exports `make_handlers()`.

2. **Logical module separation.** Handlers grouped by domain:
   - `base.py` — Core utilities, `MessageRotator`, auth checks, `_build_message_from_turn`, `_trim_messages_to_budget`
   - `files.py` — `/read`, `/write`, `/ls`, `/find`, `/set_project`, `/project_status`, `/scan_downloads`, `/organize`, `/clean`
   - `email.py` — `/gmail-unread`, `/gmail-search`, `/gmail-read`, `/gmail-labels`, `/gmail-classify`
   - `calendar.py` — `/calendar`, `/calendar-today`, `/schedule`
   - `memory.py` — `/goals`, `/plans`, `/consolidate`, `/compact`, `/delete_conversation`
   - `chat.py` — Main message handler, streaming logic, tool use processing
   - `admin.py` — `/diagnostics`, `/stats`, `/logs`, `/costs`, `/retrospective`, `/jobs`, `/reindex`, `/privacy_audit`

3. **No functional changes.** All existing tests pass without modification.

4. **Imports updated.** All consumers of `handlers.py` continue to work via the re-exported `make_handlers()`.

5. **Circular imports avoided.** Shared dependencies injected via `make_handlers()` parameters, not module-level imports.

---

## Implementation

**Files to create:**

```
remy/bot/handlers/
├── __init__.py      # Re-exports make_handlers()
├── base.py          # ~150 lines: MessageRotator, auth, message building
├── files.py         # ~400 lines: file operation handlers
├── email.py         # ~300 lines: Gmail handlers
├── calendar.py      # ~200 lines: calendar handlers
├── memory.py        # ~300 lines: goals, plans, consolidate
├── chat.py          # ~800 lines: message processing, streaming
└── admin.py         # ~400 lines: diagnostics, stats, logs
```

**Files to modify:**

- `remy/main.py` — Update import from `remy.bot.handlers` (should work unchanged due to re-export)
- `remy/bot/pipeline.py` — Update imports for `_TOOL_TURN_PREFIX`, `_build_message_from_turn`, `_trim_messages_to_budget`

### Approach

1. **Create package structure** with empty `__init__.py`.

2. **Extract `base.py`** first — contains utilities used by other modules:
   ```python
   # remy/bot/handlers/base.py
   from ...constants import WORKING_MESSAGES, TOOL_TURN_PREFIX
   
   _TOOL_TURN_PREFIX = TOOL_TURN_PREFIX
   
   class MessageRotator:
       ...
   
   def _build_message_from_turn(turn: ConversationTurn) -> dict:
       ...
   
   def _trim_messages_to_budget(messages: list[dict]) -> list[dict]:
       ...
   
   def _get_working_msg() -> str:
       ...
   ```

3. **Extract domain modules** one at a time, moving related handlers and their helper functions.

4. **Update `__init__.py`** to compose all handlers:
   ```python
   # remy/bot/handlers/__init__.py
   from .base import MessageRotator, _build_message_from_turn, _trim_messages_to_budget, _TOOL_TURN_PREFIX
   from .files import make_file_handlers
   from .email import make_email_handlers
   from .calendar import make_calendar_handlers
   from .memory import make_memory_handlers
   from .chat import make_chat_handlers
   from .admin import make_admin_handlers
   
   def make_handlers(...) -> dict:
       handlers = {}
       handlers.update(make_file_handlers(...))
       handlers.update(make_email_handlers(...))
       # ... etc
       return handlers
   ```

5. **Run tests** after each module extraction to catch regressions early.

### Notes

- The `make_handlers()` function signature should remain unchanged for backwards compatibility.
- Each domain module should define its own `make_*_handlers()` function that takes only the dependencies it needs.
- Consider using a dataclass or TypedDict for the handler dependencies to reduce parameter count.
- The `chat.py` module will be the largest (~800 lines) as it contains the main message processing logic.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Import `make_handlers` from `remy.bot.handlers` | Works unchanged |
| All existing handler tests | Pass without modification |
| `/read`, `/write`, `/ls` commands | Function correctly |
| `/gmail-*` commands | Function correctly |
| `/calendar`, `/schedule` commands | Function correctly |
| `/goals`, `/plans`, `/consolidate` commands | Function correctly |
| Main message processing with tools | Works correctly |
| `/diagnostics`, `/stats`, `/logs` commands | Function correctly |
| `pipeline.py` imports | Work correctly |

---

## Out of Scope

- Changing the handler function signatures.
- Adding new handlers or features.
- Refactoring the internal logic of individual handlers.
- Splitting `tool_registry.py` (separate user story: US-refactor-tool-registry-package).
