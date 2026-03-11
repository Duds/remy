# User Story: Native Telegram Message Threading (Topics)

<!--
Status: ✅ Done — 2026-02-28
-->

## Summary

As a user of remy, I want to use Telegram's native Message Threading (Topics) so that I can maintain separate, parallel conversation contexts within the same chat without context bleed between unrelated tasks.

---

## Background

Currently, `remy` uses a single per-user daily session key (e.g., `user_123_20260227`). This means all messages sent to the bot in a single day share the same conversation history. If a user switch from a "coding" task to a "grocery list" task, the AI's context contains irrelevant information from the previous task, which can lead to confusion or unnecessary token usage.

Telegram's "Threaded Mode" allows bots to interact within specific topics inside a private chat. This provides a natural way to silo different conversation threads.

---

## Acceptance Criteria

1. **Session Isolation:** Creating a new topic in the Telegram chat must result in a fresh conversation context.
2. **Context Persistence:** Existing threads must retain their unique history across bot restarts (until daily reset or manual compaction).
3. **Response Routing:** The bot must always respond within the same thread topic where the user's message originated.
4. **Tool Support:** Tools (like `/compact` or `/delete_conversation`) should only affect the current thread's history, not other parallel threads.
5. **Backwards Compatibility:** Standard direct messages (outside of topics) should continue using the default session-key logic.

---

## Implementation

**Files:**

- `remy/bot/session.py`
- `remy/bot/handlers.py`
- `remy/memory/conversations.py`

**Approach:**

1. Update `SessionManager.get_session_key` to accept an optional `thread_id`. The new key format should be `user_<id>_thread_<tid>_<YYYYMMDD>`.
2. In `handlers.py`'s `_process_text_input` and `handle_photo`, extract `message_thread_id` from the Telegram `Update` object.
3. Pass this `thread_id` down to the session manager.
4. Ensure all `reply_text` or `sendMessage` calls include the `message_thread_id` to ensure routing consistency.

```python
# SessionManager logic
@staticmethod
def get_session_key(user_id: int, thread_id: int | None = None) -> str:
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    if thread_id:
        return f"user_{user_id}_thread_{thread_id}_{date}"
    return f"user_{user_id}_{date}"
```

### Notes

- Requires 'Threaded Mode' to be enabled via [@BotFather](https://t.me/botfather).
- Should also implement `sendMessageDraft` for improved "natively integrated AI" streaming animations.

---

## Test Cases

| Scenario                       | Expected                                         |
| ------------------------------ | ------------------------------------------------ |
| Use General Chat               | Session key `user_123_20260227` used.            |
| Use "Research" Thread (ID 456) | Session key `user_123_thread_456_20260227` used. |
| Switch between threads         | Bot maintains isolated history for each.         |
| Delete history in thread       | Only that thread's `.jsonl` file is deleted.     |

---

## Out of Scope

- Global cross-thread memory (beyond existing Fact/Goal stores).
- Automated thread creation by the bot (user-initiated topics only for now).
