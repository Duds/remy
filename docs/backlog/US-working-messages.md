# ⬜ Backlog

# User Story: Entertaining "Working" Messages

## Summary

As Dale, I want Remy to show animated SimCity-style status messages while processing longer tasks, so I know the bot is working and get a bit of entertainment instead of a static `…`.

---

## Background

Currently handlers send a plain `…` or `_Thinking…_` placeholder when a long operation starts. The message sits static for up to 45 seconds on Board of Director requests or deep research. A rotating animated placeholder would signal liveness and be more fun.

---

## Acceptance Criteria

1. **Animated placeholder.** A "thinking" message cycles through SimCity-style phrases every ~1.2 seconds using `editMessageText` (same mechanism as `StreamingReply`).
2. **Typewriter reveal.** Each phrase is revealed progressively — first with a block cursor `▌`, then with `…` — giving a teletype effect within the rate limit budget.
3. **Rate-limit safe.** Edits fire at most once every 1.2 seconds, well below Telegram's ~20 edits/minute per chat cap.
4. **Clean teardown.** The animation task is cancelled before the real response is sent. The placeholder message is deleted (not replaced) so the real response appears as a fresh message in the chat, maintaining natural conversation flow.
5. **Opt-in per call site.** Only used for operations expected to take >3 seconds (Board, `/research`, `/retrospective`, background tasks). Fast tool calls (grocery list, calendar) keep the existing instant response.
6. **No new dependencies.** Uses `asyncio.create_task` and `bot.edit_message_text` already used in the codebase.

---

## Implementation

**New file:** `remy/bot/working_message.py`

```python
import asyncio
import itertools
import logging

logger = logging.getLogger(__name__)

_PHRASES = [
    "Reticulating splines",
    "Homologating girdles",
    "Consulting the oracle",
    "Polishing the chrome",
    "Herding cats",
    "Aligning the stars",
    "Buffering logic",
    "Generating excuses",
    "Reheating the coffee",
    "Calibrating flux capacitors",
    "Defragmenting the ether",
    "Downloading more RAM",
    "Appeasing the compiler gods",
    "Untangling the time stream",
    "Reversing the polarity",
]

class WorkingMessage:
    """Animated SimCity-style placeholder that cycles phrases via editMessageText."""

    def __init__(self, bot, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._message_id: int | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Send the initial placeholder and start the animation loop."""
        msg = await self._bot.send_message(self._chat_id, "⚙️ …")
        self._message_id = msg.message_id
        self._task = asyncio.create_task(self._animate())

    async def stop(self) -> None:
        """Cancel the animation and delete the placeholder message."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._message_id:
            try:
                await self._bot.delete_message(self._chat_id, self._message_id)
            except Exception:
                pass

    async def _animate(self) -> None:
        for phrase in itertools.cycle(_PHRASES):
            for suffix in ["▌", "…"]:
                try:
                    await self._bot.edit_message_text(
                        f"⚙️ {phrase}{suffix}",
                        self._chat_id,
                        self._message_id,
                    )
                except Exception as e:
                    logger.debug("WorkingMessage edit failed: %s", e)
                await asyncio.sleep(1.2)
```

**Usage in `handlers.py`** (Board, research, retrospective):

```python
from .working_message import WorkingMessage

# Before the long operation:
wm = WorkingMessage(context.bot, update.effective_chat.id)
await wm.start()
try:
    result = await long_operation(...)
finally:
    await wm.stop()

await update.message.reply_text(result)
```

### Notes

- `stop()` deletes the placeholder before the real reply is sent, keeping the chat timeline clean.
- The `itertools.cycle` runs indefinitely — the task is always cancelled by `stop()`, never exits on its own.
- Edit failures (e.g. message already deleted, flood control) are DEBUG-logged and skipped; the loop continues.
- This replaces the `await update.message.reply_text("_Thinking…_")` pattern at call sites — the placeholder message is the `WorkingMessage`, not a `StreamingReply`.
- For background tasks (`BackgroundTaskRunner`), `WorkingMessage` can be used before `asyncio.create_task()` fires — start it, fire the detached task, stop it when the detached task completes.

---

## Phrase List

| Phrase | Notes |
|---|---|
| Reticulating splines | SimCity classic |
| Homologating girdles | SimCity classic |
| Consulting the oracle | |
| Polishing the chrome | |
| Herding cats | |
| Aligning the stars | |
| Buffering logic | |
| Generating excuses | |
| Reheating the coffee | |
| Calibrating flux capacitors | Back to the Future |
| Defragmenting the ether | |
| Downloading more RAM | internet classic |
| Appeasing the compiler gods | |
| Untangling the time stream | |
| Reversing the polarity | Doctor Who |

Add more to `_PHRASES` freely — the list is static data, not configuration.

---

## Test Cases

| Scenario | Expected |
|---|---|
| `start()` then `stop()` immediately | Placeholder sent, then deleted; no animation frames |
| `stop()` called after 2+ seconds | At least one edit made before teardown |
| `editMessageText` raises `BadRequest` | Loop continues; error DEBUG-logged |
| Real response sent after `stop()` | Placeholder gone; real reply appears as fresh message |
| `stop()` called twice | Second call is a no-op |

---

## Out of Scope

- Per-user opt-out toggle (keep it simple).
- Streaming the real response into the working message (use `StreamingReply` for that, separately).
- Word-by-word character reveal (too many edits; 1.2s tick is the right granularity).
