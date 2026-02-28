# User Story: Refactor Primary Chat ID Storage into Shared Helper

## Summary

As a developer, I want the primary chat ID storage logic extracted into a shared helper function
so that the `/setmychat` command and `set_proactive_chat` tool don't duplicate the same code.

---

## Background

The fix for Bug 3 (`set_proactive_chat` tool not working via natural language) introduced
duplicate logic between two locations:

1. **`/setmychat` command** — `remy/bot/handlers.py` lines 365–378
2. **`set_proactive_chat` tool** — `remy/ai/tool_registry.py` lines 3492–3500

Both implementations:
- Read `settings.primary_chat_file`
- Create parent directories with `os.makedirs()`
- Write the chat ID as a string to the file

This duplication violates DRY and creates maintenance risk if the storage format changes.

---

## Proposed Solution

Extract the shared logic into a helper function:

```python
# In remy/config.py (near settings) or remy/bot/utils.py

def save_primary_chat_id(chat_id: int) -> None:
    """Save the primary chat ID for proactive messages."""
    path = settings.primary_chat_file
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(str(chat_id))
```

Then update both call sites:

**handlers.py:**
```python
async def setmychat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _reject_unauthorized(update):
        return
    chat_id = update.effective_chat.id
    try:
        save_primary_chat_id(chat_id)
        await update.message.reply_text(
            f"This chat is now set for proactive messages. (ID: {chat_id})"
        )
    except OSError as e:
        await update.message.reply_text(f"Could not save: {e}")
```

**tool_registry.py:**
```python
async def _exec_set_proactive_chat(self, user_id: int, chat_id: int | None = None) -> str:
    if chat_id is None:
        return "Setting the proactive chat requires..."
    
    from ..config import save_primary_chat_id
    try:
        save_primary_chat_id(chat_id)
        return f"✅ This chat is now set for proactive messages (ID: {chat_id})"
    except OSError as e:
        return f"❌ Could not save chat setting: {e}"
```

---

## Acceptance Criteria

1. [ ] Helper function `save_primary_chat_id()` exists in a shared location
2. [ ] `/setmychat` command uses the helper
3. [ ] `set_proactive_chat` tool uses the helper
4. [ ] Both features continue to work identically
5. [ ] No duplicate file I/O logic remains

---

## Priority

Low — this is a code quality improvement, not a bug fix.

## Effort

Small — straightforward extraction refactor.
