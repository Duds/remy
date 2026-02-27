# User Story: Background Task Runner (Fire-and-Forget)

✅ **Done** — implemented in commit b563015 (`feat: one-time reminders + BackgroundTaskRunner`)

## Summary
As a user, I do not want to wait blocked in Telegram for slow tasks like Board of Directors
analysis or retrospectives to finish. When I kick off a long-running request, Remy should
immediately acknowledge it and message me when the result is ready.

---

## Background

Slow tasks (`/board` ~45 s, `/retrospective`, deep research) currently hold the per-user
session lock for their full duration. During that time the user cannot send other messages,
and a network hiccup can drop the result entirely.

`ProactiveScheduler` already demonstrates the right pattern — it runs async AI work outside
the session lock and calls `bot.send_message()` with the result. A `BackgroundTaskRunner`
generalises this for user-triggered requests.

**This is Phase 7, Step 1 — no new infrastructure, no new dependencies.**

---

## Acceptance Criteria

1. **Immediate acknowledgement.** When a detachable request is detected, Remy replies
   "Started — I'll message you when done 🔄" within 1–2 s and releases the session lock.
2. **Result delivered via Telegram.** On completion the bot sends a new message (not an edit)
   with the full result.
3. **Failures are handled gracefully.** Exceptions in the detached task are logged; the user
   receives a brief failure notice ("Sorry, the board analysis failed — check /logs").
4. **Main conversation is not blocked.** The user can send new messages while the task runs.
5. **Detachable tasks:** `/board`, `/retrospective`, and messages classified as "deep
   analysis" by `classifier.py`.
6. **No new dependencies.** Implementation uses `asyncio.create_task()` only.

---

## Implementation

**New file:** `drbot/agents/background.py`
**Modified file:** `drbot/bot/handlers.py`

### `drbot/agents/background.py`

```python
class BackgroundTaskRunner:
    def __init__(self, bot, chat_id: int):
        self._bot = bot
        self._chat_id = chat_id

    async def run(self, coro, *, label: str) -> None:
        """Fire coro and send result/error to chat_id on completion."""
        try:
            result = await coro
            await self._bot.send_message(self._chat_id, result)
        except Exception as exc:
            logger.exception("Background task %r failed", label)
            await self._bot.send_message(
                self._chat_id,
                f"Sorry, the {label} task failed — check /logs for details.",
            )
```

### `handlers.py` — detach logic

```python
DETACHABLE_INTENTS = {"board", "retrospective", "deep_analysis"}

async def _process_text_input(...):
    intent = classifier.classify(message_text)
    if intent in DETACHABLE_INTENTS:
        async with session_lock:
            await reply.send("Started — I'll message you when done 🔄")
        runner = BackgroundTaskRunner(bot, chat_id)
        asyncio.create_task(runner.run(_exec_board(...), label="board analysis"))
        return
    # existing path continues unchanged
```

---

## Test Cases

| Scenario | Expected |
|---|---|
| User sends `/board` | Immediate "Started…" reply; board result arrives separately |
| User sends `/retrospective` | Same fire-and-forget pattern |
| Background task throws an exception | User notified with failure message; no crash |
| User sends a new message while board is running | Response is not blocked |
| Non-detachable request | Existing synchronous path unchanged |

---

## Out of Scope

- Persistent tracking across bot restarts (Phase 7, Step 2 — see `US-persistent-job-tracking`)
- `/jobs` status command (Phase 7, Step 2)
- Claude Agent SDK subagents (Phase 7, Step 3)
