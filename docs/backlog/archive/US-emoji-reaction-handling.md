# User Story: Emoji Reaction Handling

Phase 1 ✅ Done — 2026-03-02 (inbound: Dale → Remy)
Phase 2 ✅ Done — 2026-03-02 (outbound: Remy → Dale)

## Summary

As Dale, I want emoji reactions to be a two-way channel between me and Remy:
- **Inbound** — I can react to Remy's messages as lightweight signals (approval, confusion, enthusiasm) and Remy will acknowledge them naturally.
- **Outbound** — Remy can react to my messages with emoji to acknowledge, confirm, or express tone without necessarily sending a full reply.

---

## Background

Telegram supports emoji reactions on messages (❤️, 👍, 👎, 🔥, 🤔, etc.). Reactions are a natural, low-friction communication channel. A thumbs-up on a task report says "got it, done." A heart on a morning briefing says "I saw it, good." A fire on a plan says "yes, let's do this."

`python-telegram-bot` v22+ supports both directions:
- **Receiving** reactions via `MessageReactionHandler` + `MessageReactionUpdated`
- **Setting** reactions on messages via `bot.set_message_reaction(chat_id, message_id, [ReactionTypeEmoji(emoji)])`

---

## Phase 1 — Inbound: Dale reacts to Remy's messages ✅

### Acceptance Criteria

1. **Reactions are received.** Remy registers a `MessageReactionHandler` and the bot's allowed update types include `message_reaction`.
2. **Reactions on Remy's own messages only.** Reactions on messages Remy did not send are ignored.
3. **Authorisation enforced.** Reactions from users not in `TELEGRAM_ALLOWED_USERS` are silently ignored.
4. **Reaction-to-text mapping.** Common emojis are mapped to a natural-language context string passed to Claude.
5. **Reaction removal is a no-op.** If `new_reaction` is empty (reaction removed), Remy does not respond.
6. **Remy replies in-context.** Brief, natural reply in Remy's voice — warm, concise, no waffle.
7. **Reaction is injected into conversation history** as a user turn.
8. **No double-firing.** Reactions and typed messages processed independently without collision.
9. **Logged** at DEBUG level.

### Implementation (complete)

- `remy/bot/handlers/reactions.py` — `make_reaction_handler()` factory
- `remy/bot/telegram_bot.py` — `MessageReactionHandler` registered; `run_polling(allowed_updates=Update.ALL_TYPES)`
- `remy/bot/handlers/__init__.py` — wired into `make_handlers()`

### Example Interactions

```
Dale reacts 👍 to Remy's Gmail summary
→ Remy: "Glad that was useful, Doc."

Dale reacts ❤️ to Remy's morning briefing
→ Remy: "Morning sorted. Go get 'em."

Dale reacts 👎 to a task result
→ Remy: "Noted — what went wrong? I can have another go."

Dale reacts 🤔 to a research summary
→ Remy: "Want me to dig deeper on any part of that?"

Dale reacts 🔥 to a plan Remy drafted
→ Remy: "Let's do it. Want me to kick it off?"
```

---

## Phase 2 — Outbound: Remy reacts to Dale's messages ✅

### Acceptance Criteria

1. **Remy can set reactions on Dale's messages.** `bot.set_message_reaction()` is called with a `ReactionTypeEmoji` when appropriate.
2. **Claude decides when to react.** Reaction-setting is exposed as a Claude-callable tool `react_to_message(emoji, message_id)` registered in `ToolRegistry`. Claude calls it autonomously when it judges a reaction is appropriate instead of (or in addition to) a text reply.
3. **Reaction replaces reply for simple acknowledgements.** When Claude reacts with 👍 or ✅, it may omit a text reply entirely — the reaction is the acknowledgement.
4. **Curated outbound emoji set.** Claude is instructed to choose only from a small, semantically clear set:

   | Emoji | When to use |
   |-------|-------------|
   | 👍 | Task understood, acknowledged, will do |
   | ✅ | Task complete |
   | ❤️ | Warm moment, emotional support |
   | 🔥 | Enthusiastic agreement, great idea |
   | 🤔 | Need to think about this / not sure |
   | 😂 | Genuinely funny |
   | 👀 | Noted, watching this |
   | 🎉 | Celebrating an achievement |

5. **message_id is available.** The `handle_message` handler passes the incoming message ID into the Claude context so the tool can reference it.
6. **Fallback gracefully.** If `set_message_reaction` fails (e.g. message too old, permission error), log a WARNING and continue — never raise to the user.
7. **Not overused.** Claude guidance in SOUL.md should discourage reacting to every message. Reactions are occasional, meaningful, not reflexive.

### Implementation (complete)

#### Tool: `react_to_message`

Add to `remy/ai/tools/` (or inline in `ToolRegistry`):

```python
async def react_to_message(emoji: str, message_id: int, chat_id: int, bot) -> str:
    """Set an emoji reaction on a Telegram message."""
    from telegram import ReactionTypeEmoji
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
        return f"Reacted with {emoji}"
    except Exception as e:
        logger.warning("set_message_reaction failed: %s", e)
        return f"Could not react: {e}"
```

#### Tool schema

```json
{
  "name": "react_to_message",
  "description": "Set an emoji reaction on Dale's most recent message. Use instead of or alongside a text reply for simple acknowledgements. Only use when a reaction meaningfully communicates something — not as a reflex.",
  "input_schema": {
    "type": "object",
    "properties": {
      "emoji": {
        "type": "string",
        "description": "The emoji to react with. Must be one of: 👍 ✅ ❤️ 🔥 🤔 😂 👀 🎉"
      }
    },
    "required": ["emoji"]
  }
}
```

The tool implementation reads `chat_id` and `message_id` from context (passed via the tool execution environment), so Claude only needs to specify the emoji.

#### Context injection

In `handle_message`, before building the messages array, inject the current message ID into the system prompt or as a hint:

```python
system_prompt += f"\n\n<context>Dale's current message_id: {update.message.message_id}</context>"
```

#### SOUL.md guidance

Add a brief section on when to use reactions vs text replies:
- Use 👍 or ✅ when confirming a simple instruction — no need for "Got it, Doc."
- Use ❤️ on warm or emotional messages when a reaction feels more genuine than words
- Don't react to every message — that's noise
- Never react AND send a hollow acknowledgement text

---

## Reaction Map (shared, both directions)

| Emoji | Inbound meaning (Dale → Remy) | Outbound use (Remy → Dale) |
|-------|-------------------------------|----------------------------|
| 👍 | approval / understood | task acknowledged |
| ❤️ | warm, positive | warmth, emotional support |
| 🔥 | excited, this is great | enthusiastic agreement |
| 👎 | disagreement or disappointment | — (Remy won't use this) |
| 🤔 | uncertain, wants more info | not sure, need to think |
| 😂 | found it funny | genuinely funny |
| 😢 | feels bad about this | — (too sad, Remy won't use) |
| 🎉 | celebrating | celebrating achievement |
| 🎊 | celebrating | — |
| 💯 | full agreement | — |
| 🙏 | grateful | — |
| 👀 | curious, paying attention | noted, watching |
| ✅ | done / confirmed | task complete |
| ❌ | no / rejected | — (Remy won't use) |

---

## Out of Scope

- Custom/animated emoji (mapped to generic fallback for inbound; excluded from outbound set).
- Storing reaction history in a DB table (conversation turns are sufficient).
- Multiple simultaneous reactions (first emoji wins inbound; Remy sends one emoji outbound).
- Reactions on messages older than 24 hours (Telegram API limitation).

---

## Test Cases

### Phase 1 (Inbound)

| Scenario | Expected |
|----------|----------|
| Authorised user reacts 👍 to a Remy message | Remy replies with brief acknowledgement |
| Authorised user removes a reaction | No response from Remy |
| Unauthorised user reacts to any message | Silent ignore |
| Reaction on a message Dale sent | Silent ignore |
| Unknown emoji reaction | Generic context, Remy replies naturally |
| Reaction arrives while another request is processing | Handled independently |
| `new_reaction` contains multiple emojis | First emoji is used |

### Phase 2 (Outbound)

| Scenario | Expected |
|----------|----------|
| Dale says "ok delete that email" | Remy reacts 👍, proceeds with action |
| Dale shares good news | Remy reacts 🎉 or ❤️ and/or sends a warm reply |
| `set_message_reaction` raises API error | WARNING logged, conversation continues |
| Claude uses reaction AND sends text | Both are sent — reaction first |
| Claude reacts to every message | SOUL.md guidance prevents this — occasional use only |