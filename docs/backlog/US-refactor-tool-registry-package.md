# User Story: Refactor tool_registry.py into Package

**Status:** ⬜ Backlog

**Priority:** P1

## Summary

As a developer, I want to split `remy/ai/tool_registry.py` (4,000+ lines) into a modular package structure so that tool implementations are easier to find, test, and extend.

---

## Background

The `tool_registry.py` file has grown to over 4,000 lines containing 60+ tool executor methods and a massive `TOOL_SCHEMAS` list. This monolithic structure makes it difficult to:

- Add new tools without navigating a huge file
- Test tool executors in isolation
- Understand which tools are related
- Review changes that touch multiple tool domains

The March 2026 engineering review identified this as a P2 refactoring priority. The file currently contains:

- **Tool schemas**: `TOOL_SCHEMAS` list (~1,200 lines of JSON-like dicts)
- **ToolRegistry class**: Dispatch logic and constructor (~100 lines)
- **Time executors**: `_exec_get_current_time`
- **Memory executors**: `_exec_get_goals`, `_exec_get_facts`, `_exec_manage_memory`, `_exec_manage_goal`, `_exec_get_memory_summary`
- **Calendar executors**: `_exec_calendar_events`, `_exec_create_calendar_event`
- **Email executors**: `_exec_read_emails`, `_exec_search_gmail`, `_exec_read_email`, `_exec_list_gmail_labels`, `_exec_label_emails`, `_exec_create_gmail_label`, `_exec_create_email_draft`, `_exec_classify_promotional`
- **Contacts executors**: `_exec_search_contacts`, `_exec_upcoming_birthdays`, `_exec_get_contact_details`, `_exec_update_contact_note`, `_exec_find_sparse_contacts`
- **File executors**: `_exec_read_file`, `_exec_list_directory`, `_exec_write_file`, `_exec_append_file`, `_exec_find_files`, `_exec_scan_downloads`, `_exec_organize_directory`, `_exec_clean_directory`, `_exec_search_files`, `_exec_index_status`
- **Web executors**: `_exec_web_search`, `_exec_price_check`
- **Automation executors**: `_exec_schedule_reminder`, `_exec_set_one_time_reminder`, `_exec_list_reminders`, `_exec_remove_reminder`, `_exec_breakdown_task`
- **Plan executors**: `_exec_create_plan`, `_exec_get_plan`, `_exec_list_plans`, `_exec_update_plan_step`, `_exec_update_plan_status`
- **Analytics executors**: `_exec_get_stats`, `_exec_get_goal_status`, `_exec_generate_retrospective`, `_exec_get_costs`, `_exec_consolidate_memory`, `_exec_list_background_jobs`
- **Session executors**: `_exec_compact_conversation`, `_exec_delete_conversation`, `_exec_set_proactive_chat`
- **Special executors**: `_exec_trigger_reindex`, `_exec_start_privacy_audit`

---

## Acceptance Criteria

1. **Package structure created.** `remy/ai/tools/` directory with `__init__.py` that re-exports `ToolRegistry`.

2. **Logical module separation.** Tools grouped by domain:
   - `schemas.py` — `TOOL_SCHEMAS` list (can be split further if needed)
   - `registry.py` — `ToolRegistry` class with dispatch logic
   - `time.py` — Time-related executors
   - `memory.py` — Memory/knowledge executors
   - `calendar.py` — Calendar executors
   - `email.py` — Gmail executors
   - `contacts.py` — Contacts executors
   - `files.py` — File operation executors
   - `web.py` — Web search executors
   - `automations.py` — Automation/reminder executors
   - `plans.py` — Plan executors
   - `analytics.py` — Analytics executors
   - `session.py` — Session management executors

3. **No functional changes.** All existing tests pass without modification.

4. **Imports updated.** All consumers of `tool_registry.py` continue to work via the re-exported `ToolRegistry`.

5. **Dispatch mechanism preserved.** The `dispatch()` method continues to route tool calls correctly.

---

## Implementation

**Files to create:**

```
remy/ai/tools/
├── __init__.py      # Re-exports ToolRegistry
├── schemas.py       # ~1,200 lines: TOOL_SCHEMAS list
├── registry.py      # ~200 lines: ToolRegistry class with dispatch
├── time.py          # ~50 lines: time executors
├── memory.py        # ~300 lines: memory/knowledge executors
├── calendar.py      # ~150 lines: calendar executors
├── email.py         # ~400 lines: Gmail executors
├── contacts.py      # ~200 lines: contacts executors
├── files.py         # ~500 lines: file operation executors
├── web.py           # ~150 lines: web search executors
├── automations.py   # ~250 lines: automation executors
├── plans.py         # ~200 lines: plan executors
├── analytics.py     # ~300 lines: analytics executors
└── session.py       # ~150 lines: session management executors
```

**Files to modify:**

- `remy/main.py` — Update import from `remy.ai.tool_registry` to `remy.ai.tools` (should work unchanged due to re-export)
- `remy/bot/handlers.py` — Update import if needed
- `remy/diagnostics/runner.py` — Update import if needed

### Approach

1. **Create package structure** with `__init__.py` that re-exports `ToolRegistry`.

2. **Extract `schemas.py`** first — the `TOOL_SCHEMAS` list is independent:
   ```python
   # remy/ai/tools/schemas.py
   TOOL_SCHEMAS = [
       {
           "name": "get_current_time",
           "description": "...",
           ...
       },
       # ... all tool schemas
   ]
   ```

3. **Create executor base class** (optional but recommended):
   ```python
   # remy/ai/tools/base.py
   from abc import ABC, abstractmethod
   
   class ToolExecutor(ABC):
       def __init__(self, registry: "ToolRegistry"):
           self._registry = registry
       
       @abstractmethod
       async def execute(self, inp: dict, user_id: int) -> str:
           pass
   ```

4. **Extract domain executor modules** one at a time:
   ```python
   # remy/ai/tools/email.py
   import logging
   from typing import TYPE_CHECKING
   
   if TYPE_CHECKING:
       from .registry import ToolRegistry
   
   logger = logging.getLogger(__name__)
   
   async def exec_read_emails(registry: "ToolRegistry", inp: dict, user_id: int) -> str:
       ...
   
   async def exec_search_gmail(registry: "ToolRegistry", inp: dict, user_id: int) -> str:
       ...
   ```

5. **Update `registry.py`** to import and dispatch to executor functions:
   ```python
   # remy/ai/tools/registry.py
   from .schemas import TOOL_SCHEMAS
   from . import email, calendar, memory, files, web, automations, plans, analytics, session, time
   
   class ToolRegistry:
       def __init__(self, ...):
           ...
       
       @property
       def schemas(self) -> list[dict]:
           return TOOL_SCHEMAS
       
       async def dispatch(self, tool_name: str, inp: dict, user_id: int) -> str:
           match tool_name:
               case "read_emails":
                   return await email.exec_read_emails(self, inp, user_id)
               case "search_gmail":
                   return await email.exec_search_gmail(self, inp, user_id)
               # ... etc
   ```

6. **Update `__init__.py`** to re-export:
   ```python
   # remy/ai/tools/__init__.py
   from .registry import ToolRegistry
   from .schemas import TOOL_SCHEMAS
   
   __all__ = ["ToolRegistry", "TOOL_SCHEMAS"]
   ```

7. **Run tests** after each module extraction to catch regressions early.

### Notes

- The `ToolRegistry` constructor signature should remain unchanged for backwards compatibility.
- Each executor function receives the registry instance to access shared dependencies (e.g., `registry._gmail`, `registry._calendar`).
- Consider using Python 3.10+ `match` statement for cleaner dispatch logic.
- The `schemas.py` file will still be large (~1,200 lines) but is pure data and rarely changes.
- Alternative: Split schemas by domain too (e.g., `schemas/email.py`, `schemas/calendar.py`).

---

## Test Cases

| Scenario | Expected |
|---|---|
| Import `ToolRegistry` from `remy.ai.tools` | Works unchanged |
| Import `ToolRegistry` from `remy.ai.tool_registry` | Works via re-export |
| All existing tool tests | Pass without modification |
| `dispatch("read_emails", ...)` | Returns email summary |
| `dispatch("calendar_events", ...)` | Returns calendar events |
| `dispatch("manage_memory", ...)` | Manages memory correctly |
| `dispatch("web_search", ...)` | Returns search results |
| `dispatch("create_plan", ...)` | Creates plan correctly |
| Unknown tool name | Returns appropriate error message |

---

## Out of Scope

- Changing the tool schemas or adding new tools.
- Modifying the dispatch mechanism (e.g., switching to a plugin system).
- Refactoring individual executor implementations.
- Splitting `handlers.py` (separate user story: US-refactor-handlers-package).
