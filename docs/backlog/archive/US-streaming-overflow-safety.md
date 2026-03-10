# User Story: Streaming Reply Overflow Split Safety

**Status:** ✅ Done (Completed: 2026-03-10)

## Summary

As a developer, I want the streaming reply overflow path to include a debug-mode length assertion so that any edge-case message exceeding Telegram's 4096-character hard limit is caught immediately during development rather than silently failing in production.

---

## Background

`StreamingReply._flush()` in `remy/bot/streaming.py` splits messages that exceed `_TELEGRAM_MAX_LEN` (4000 chars). The split uses `rfind(" ", 0, _TELEGRAM_MAX_LEN)` to find the last space before the limit; if no space is found it falls back to a hard split at exactly 4000 chars.

The in-progress suffix `" …"` is pre-appended to `display` before the overflow check, which means `display` can be up to `len(accumulated_text) + 2` chars. In the worst-case, a hard split at 4000 chars produces a 4000-char part followed by a leftover part containing only the final 1–2 characters (e.g. just `"…"`). Neither part violates Telegram's 4096-char limit in practice, but the logic has not been formally verified under all edge cases and there is no failing test to catch regressions.

Priority is low — the current code has not caused visible failures — but the assertion would make the invariant explicit and catch future regressions immediately.

Related to Bug 14 in `BUGS.md`.

---

## Acceptance Criteria

1. **Debug assertion present.** After each `_edit_or_skip(part)` call in the overflow loop, an assertion (or DEBUG-level check) verifies `len(part) <= 4096`.
2. **Assertion is gated.** The check only runs when Python is started with `-O` flag absent (i.e. standard `assert` semantics) or when `LOG_LEVEL=DEBUG`. It is a no-op in optimised production builds.
3. **No behaviour change.** Message splitting logic is unchanged; the assertion is purely a guard.
4. **Existing tests pass.** `tests/test_streaming.py` (or equivalent) continues to pass.

---

## Implementation

**Files:** `remy/bot/streaming.py` — `_flush()` method, overflow while-loop.

Add the assertion immediately after computing `part`:

```python
while len(display) > _TELEGRAM_MAX_LEN:
    split_at = display.rfind(" ", 0, _TELEGRAM_MAX_LEN)
    if split_at < 0:
        split_at = _TELEGRAM_MAX_LEN
    part = display[:split_at]
    assert len(part) <= 4096, f"Overflow split produced {len(part)}-char message (limit 4096)"
    display = display[split_at:].lstrip()
    await self._edit_or_skip(part)
    # ... create new overflow message ...
```

Alternatively, replace the `assert` with a conditional log if the team prefers not to raise in production:

```python
if len(part) > 4096:
    logger.error(
        "BUG: overflow split produced %d-char message (limit 4096); truncating",
        len(part),
    )
    part = part[:4096]
```

### Notes

- `_TELEGRAM_MAX_LEN = 4000` gives 96 chars of headroom below Telegram's actual limit. The suffix `" …"` is only 2 chars. The headroom is sufficient; this story is purely defensive.
- Consider also asserting `len(display) <= 4096` at the end of `_flush()` (after the loop) to cover the non-overflow path.
- `_TELEGRAM_MAX_LEN` is defined at module level — confirm its value is 4000 before adding the assertion.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Message exactly 4000 chars, no suffix | No split; sent as-is |
| Message 3999 chars + `" …"` suffix (4001 total) | Split fires; part ≤ 4000 chars; assertion passes |
| Message with no spaces near the 4000-char boundary | Hard split at 4000; assertion passes; leftover sent as new message |
| Part somehow exceeds 4096 chars | `assert` raises `AssertionError` (dev) or ERROR log + truncation (prod) |

---

## Out of Scope

- Changing the split strategy (e.g. splitting at sentences rather than spaces) — not needed at current scale.
- Measuring message length in UTF-16 code units to match Telegram's internal counting — out of scope; Python `len()` is close enough for practical purposes.
