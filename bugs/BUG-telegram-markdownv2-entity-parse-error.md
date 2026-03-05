# BUG: Telegram MarkdownV2 Entity Parse Error

**Date:** 2026-03-04  
**Severity:** Medium — causes message failure, Anthropic retry, and Telegram disconnect  
**Status:** Open

---

## Summary

Telegram is rejecting messages with a MarkdownV2 entity parse error:  
`Can't find end of entity at byte offset 668`

This causes:
1. The message to fail to send
2. Anthropic client to retry (observed at 11:36:59)
3. Telegram to disconnect (observed at 11:37:03)
4. User-visible sluggishness / delay

---

## Observed Pattern (from logs)

- 3+ Telegram `Server disconnected without sending a response` errors in a 6h window
- `stream_with_tools` hitting max iterations (6) twice — suggests retries compounding the issue
- Sequence: Anthropic retry → Telegram disconnect → reconnect overhead = felt latency

---

## Hypothesis

The space-dropping fix applied earlier today may be the root cause. Likely mechanisms:

1. **Stripped delimiter space** — Telegram requires a space (or punctuation) before/after formatting markers (`*`, `_`, `` ` ``). If the fix strips a space adjacent to a marker, the entity becomes malformed.
2. **Byte offset shift** — Removing characters shifts byte positions, causing a closing marker to land next to an unescaped special character (e.g. `.`, `!`, `-`), which Telegram's parser rejects.
3. **Unclosed entity** — If a space between two formatted words is removed and they merge, a closing `*` may now be interpreted as an opening one, leaving an entity unclosed.

---

## Reproduction

Trigger a response containing bold or italic MarkdownV2 formatting in a context where the space-fix would activate (e.g. end of a word followed by punctuation). Check if Telegram rejects the message.

---

## Suggested Fix

- Review the space-dropping fix and add a guard: do not strip spaces that are immediately adjacent to MarkdownV2 formatting markers (`*`, `_`, `[`, `]`, `` ` ``, `~`, `||`)
- Add a MarkdownV2 entity validator before sending — verify all opened entities are closed before dispatching to Telegram
- Log the full message body when a Telegram 400 Bad Request occurs, to capture the exact failing string

---

## Related

- `remy.ai.claude_client` max iterations warning (x2) — may be retry storm triggered by this error
- Telegram transient disconnect warnings — downstream effect of parse error causing bad request

---

*Logged by Remy*
