# User Story: Extract Briefing Generators from proactive.py

**Status:** ✅ Done

**Priority:** P1

## Summary

As a developer, I want to extract the briefing generation logic from `remy/scheduler/proactive.py` into a dedicated `remy/scheduler/briefings/` package so that briefing templates are easier to customise, test, and extend.

---

## Background

The `proactive.py` file (~900 lines) contains the `ProactiveScheduler` class which mixes scheduling infrastructure with briefing content generation. The briefing methods (`_morning_briefing`, `_afternoon_focus`, `_evening_checkin`, `_monthly_retrospective`) contain:

- Data fetching logic (goals, calendar, contacts, downloads)
- Template formatting and string building
- Claude prompt construction for synthesis
- Conditional sections based on available data

This coupling makes it difficult to:

- Test briefing content generation in isolation
- Customise briefing templates without touching scheduler code
- Add new briefing types (e.g., weekly summary, project status)
- Understand the scheduler's core responsibility (timing) vs content generation

The March 2026 engineering review identified this as a P2 refactoring priority.

Current briefing methods:
- `_morning_briefing()` — ~85 lines: goals, calendar, birthdays, downloads, stale plans
- `_afternoon_focus()` — ~50 lines: ADHD body-double nudge with goals
- `_evening_checkin()` — ~40 lines: stale goals nudge
- `_monthly_retrospective()` — ~25 lines: Claude-generated monthly summary
- `_downloads_suggestion()` — ~15 lines: helper for downloads section
- `_stale_plan_steps()` — ~30 lines: helper for stale plan steps

---

## Acceptance Criteria

1. **Package structure created.** `remy/scheduler/briefings/` directory with `__init__.py`.

2. **Logical module separation.** Briefing generators as independent classes:
   - `base.py` — `BriefingGenerator` base class with common utilities
   - `morning.py` — `MorningBriefingGenerator` class
   - `afternoon.py` — `AfternoonFocusGenerator` class
   - `evening.py` — `EveningCheckinGenerator` class
   - `retrospective.py` — `MonthlyRetrospectiveGenerator` class

3. **Clean interface.** Each generator has a simple `async def generate(self) -> str` method.

4. **Dependency injection.** Generators receive their dependencies (stores, clients) via constructor.

5. **No functional changes.** All existing briefing content remains identical.

6. **Scheduler simplified.** `ProactiveScheduler` delegates to generators, reducing its size by ~200 lines.

---

## Implementation

**Files to create:**

```
remy/scheduler/briefings/
├── __init__.py           # Re-exports generator classes
├── base.py               # ~50 lines: BriefingGenerator base class
├── morning.py            # ~120 lines: MorningBriefingGenerator
├── afternoon.py          # ~80 lines: AfternoonFocusGenerator
├── evening.py            # ~60 lines: EveningCheckinGenerator
└── retrospective.py      # ~50 lines: MonthlyRetrospectiveGenerator
```

**Files to modify:**

- `remy/scheduler/proactive.py` — Import and use generators, remove inline briefing logic

### Approach

1. **Create base class** with shared utilities:
   ```python
   # remy/scheduler/briefings/base.py
   from abc import ABC, abstractmethod
   from typing import TYPE_CHECKING
   
   if TYPE_CHECKING:
       from ...memory.goals import GoalStore
       from ...memory.plans import PlanStore
       from ...memory.file_index import FileIndexer
       from ...google.calendar import CalendarClient
       from ...google.contacts import ContactsClient
       from ...ai.claude_client import ClaudeClient
   
   class BriefingGenerator(ABC):
       def __init__(
           self,
           user_id: int,
           goal_store: "GoalStore | None" = None,
           plan_store: "PlanStore | None" = None,
           calendar: "CalendarClient | None" = None,
           contacts: "ContactsClient | None" = None,
           file_indexer: "FileIndexer | None" = None,
           claude: "ClaudeClient | None" = None,
       ):
           self._user_id = user_id
           self._goal_store = goal_store
           self._plan_store = plan_store
           self._calendar = calendar
           self._contacts = contacts
           self._file_indexer = file_indexer
           self._claude = claude
       
       @abstractmethod
       async def generate(self) -> str:
           """Generate the briefing content."""
           pass
       
       async def _get_active_goals(self) -> list[str]:
           """Fetch active goals for the user."""
           if not self._goal_store:
               return []
           goals = await self._goal_store.list_goals(self._user_id)
           return [g.goal for g in goals if g.status == "active"]
       
       async def _get_stale_goals(self, days: int = 3) -> list[str]:
           """Fetch goals not updated within N days."""
           ...
   ```

2. **Extract `MorningBriefingGenerator`**:
   ```python
   # remy/scheduler/briefings/morning.py
   from datetime import datetime, timedelta
   from .base import BriefingGenerator
   
   class MorningBriefingGenerator(BriefingGenerator):
       async def generate(self) -> str:
           sections = []
           
           # Goals section
           goals = await self._get_active_goals()
           if goals:
               sections.append(self._format_goals_section(goals))
           
           # Calendar section
           events = await self._get_todays_events()
           if events:
               sections.append(self._format_calendar_section(events))
           
           # Birthdays section
           birthdays = await self._get_upcoming_birthdays()
           if birthdays:
               sections.append(self._format_birthdays_section(birthdays))
           
           # Downloads section
           downloads = await self._get_downloads_suggestion()
           if downloads:
               sections.append(downloads)
           
           # Stale plans section
           stale = await self._get_stale_plan_steps()
           if stale:
               sections.append(stale)
           
           return "\n\n".join(sections) if sections else "Good morning! No updates today."
       
       def _format_goals_section(self, goals: list[str]) -> str:
           ...
       
       async def _get_todays_events(self) -> list[dict]:
           ...
   ```

3. **Update `ProactiveScheduler`** to use generators:
   ```python
   # remy/scheduler/proactive.py
   from .briefings import MorningBriefingGenerator, AfternoonFocusGenerator, EveningCheckinGenerator
   
   class ProactiveScheduler:
       async def _morning_briefing(self) -> None:
           chat_id = _read_primary_chat_id()
           if not chat_id:
               return
           
           generator = MorningBriefingGenerator(
               user_id=chat_id,
               goal_store=self._goal_store,
               plan_store=self._plan_store,
               calendar=self._calendar,
               contacts=self._contacts,
               file_indexer=self._file_indexer,
               claude=self._claude,
           )
           
           content = await generator.generate()
           await self._send(chat_id, content)
   ```

4. **Run tests** after each generator extraction.

### Notes

- The generators should be stateless — all state comes from the stores/clients passed in.
- Consider adding a `BriefingConfig` dataclass for customisation (e.g., stale goal threshold, birthday lookahead days).
- The `_downloads_suggestion()` and `_stale_plan_steps()` helpers can become methods on `MorningBriefingGenerator`.
- Future enhancement: Allow users to customise which sections appear in their briefings.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Morning briefing with goals, calendar, birthdays | All sections rendered correctly |
| Morning briefing with no goals | Goals section omitted |
| Morning briefing with no calendar events | Calendar section omitted |
| Afternoon focus with active goals | Goals listed with encouragement |
| Afternoon focus with no goals | Generic encouragement message |
| Evening check-in with stale goals | Stale goals listed |
| Evening check-in with no stale goals | No message sent |
| Monthly retrospective | Claude synthesis generated |
| Generator with missing dependencies | Graceful handling (empty sections) |

---

## Out of Scope

- Adding new briefing types (e.g., weekly summary).
- User-configurable briefing sections.
- Changing briefing content or formatting.
- Refactoring `handlers.py` (separate user story: US-refactor-handlers-package).
- Refactoring `tool_registry.py` (separate user story: US-refactor-tool-registry-package).
