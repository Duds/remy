# Remy Bug Tracker

---

## Bug Report Template

```markdown
### BUG-XXX — Short descriptive title

| Field           | Value                                     |
| --------------- | ----------------------------------------- |
| **Date**        | YYYY-MM-DD                                |
| **Reported by** | Dale / Remy / test suite                  |
| **Severity**    | Critical / High / Medium / Low            |
| **Status**      | Open / In Progress / Fixed / Won't Fix    |
| **Component**   | e.g. bot/handlers.py, ai/claude_client.py |
| **Related**     | Link to US, PR, or other bug              |

**Description**
What is happening, and what should be happening instead.

**Steps to Reproduce**

1. Step one
2. Step two
3. Observe the problem

**Expected Behaviour**
What should happen.

**Actual Behaviour**
What actually happens.

**Suspected Cause**
Any hypothesis about root cause — or "Unknown".

**Notes**
Anything else relevant: workarounds, frequency, environment quirks.
```

---

## Closed Bugs

### BUG-002 — Reminders created mid-session are not fired by the scheduler

| Field           | Value                                                                                          |
| --------------- | ---------------------------------------------------------------------------------------------- |
| **Date**        | 2026-02-27                                                                                     |
| **Reported by** | Dale / Remy                                                                                    |
| **Severity**    | High                                                                                           |
| **Status**      | Fixed                                                                                          |
| **Component**   | `scheduler/proactive.py`, `ai/tool_registry.py`, `memory/automations.py`, `memory/database.py` |
| **Related**     | —                                                                                              |

**Description**
Reminders created via `schedule_reminder` after bot startup were saved to the database but never fired. The scheduler only registered reminders it knew about at startup. Additionally, there was no mechanism for one-time reminders ("remind me in 1 minute").

**Fix**
Two-part fix:

1. The existing `_exec_schedule_reminder` already called `sched.add_automation()` for live registration of recurring jobs — confirmed working.
2. Added full one-time reminder support:
   - Added `fire_at TEXT` column to the `automations` table via an idempotent migration in `database.py`.
   - Updated `AutomationStore.add()` to accept an optional `fire_at` datetime string; added `AutomationStore.delete()` for post-fire cleanup.
   - Updated `ProactiveScheduler._register_automation_job()` to use APScheduler's `DateTrigger` when `fire_at` is set; one-time jobs delete themselves from the DB after firing.
   - Added `set_one_time_reminder` Claude tool so Remy can handle "remind me in X minutes / at HH:MM" requests natively.

---

### BUG-001 — Inter-tool text fragments leak into Telegram stream

| Field           | Value                                 |
| --------------- | ------------------------------------- |
| **Date**        | 2026-02-27                            |
| **Reported by** | Dale                                  |
| **Severity**    | Low                                   |
| **Status**      | Fixed                                 |
| **Component**   | `bot/handlers.py` — Path A event loop |
| **Related**     | `US-tool-status-text-leak.md`         |
| **Fixed in**    | commit `7dabac3`                      |

**Description**
Claude's internal status fragments (e.g. "using list_directory", "let me check that") appeared verbatim in Telegram replies. A related symptom was narration lines being repeated: text emitted before a tool call was re-emitted after the tool result returned.

**Fix**
Introduced `in_tool_turn` boolean flag in `_stream_with_tools_path()`. Set to `True` on `ToolStatusChunk`, cleared on `ToolTurnComplete`. `TextChunk` events arriving while `in_tool_turn` is `True` are suppressed (DEBUG-logged only, not fed to `current_display`). `current_display` is reset to `[]` on each `ToolTurnComplete` to prevent pre-tool preamble from being repeated after tool results.

---

## Open Bugs

_(none)_
