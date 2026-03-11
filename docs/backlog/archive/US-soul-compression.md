# User Story: Soul Compression for Token Efficiency

<!--
Status: ✅ Done — 2026-02-28
-->

## Summary
As a developer, I want to compress Remy's SOUL.md system prompt into a more token-efficient format
so that every API call uses fewer input tokens without sacrificing personality fidelity or
behavioural consistency.

---

## Background

The current `SOUL.md` is a human-readable Markdown document (~130 lines, ~3,500 characters in the
example template). This file is injected verbatim as the system prompt on every Claude API call.
With hundreds of daily interactions, even modest token savings compound significantly.

### Current implementation

- `config.py` loads `SOUL.md` via `soul_md` property and caches it
- `MemoryInjector.build_system_prompt()` concatenates SOUL.md + memory block
- `claude_client.py` uses this as the system prompt for every call

### Token cost analysis

A typical SOUL.md might contain:
- ~800–1,200 tokens (depending on personality detail)
- Repeated structural elements: headers, dividers, formatting instructions
- Verbose explanations that Claude already understands implicitly

**Potential savings:** 40–60% reduction (320–720 tokens per call)

---

## Format Options Analysis

### Option 1: Compressed Markdown (Recommended)

Strip structural fluff while keeping natural language:

```markdown
# Remy — Dale's AI agent
Digital construct, not a person. No hedging, no apologies. 24/7 Telegram, persistent memory.

## Voice
Warm but direct. Dry wit. No sycophancy. Australian English, metric, 24h time.

## Principles
1. Memory is core — use facts naturally
2. Brevity is respect
3. Honest disagreement > false agreement
4. State limitations plainly

## Context
Dale: Canberra AU (Australia/Sydney). Primary: claude-sonnet-4-20250514, fallback: haiku.

## Capabilities
Email triage • Calendar • Goal tracking • Shopping lists • Reminders

## Commands
/help /cancel /status /goals /logs

## Limits
No: arbitrary code, system dirs, .env/.ssh/.aws, rate limit bypass
Yes: report degradation, rate limits, timeouts

## Telegram
MarkdownV2: *bold* _italic* `code` ||spoiler|| [link](url)
No headers/tables. Natural reminder refs (not IDs).
```

**Pros:** Human-editable, version-controllable, ~50% smaller
**Cons:** Still some redundancy

### Option 2: Structured YAML

```yaml
identity:
  name: Remy
  owner: Dale
  nature: AI agent, digital construct
  stance: No hedging, no apologies

voice:
  tone: warm, direct
  wit: dry
  sycophancy: none
  locale: en-AU
  units: metric
  time: 24h

principles:
  - Memory is core
  - Brevity is respect
  - Honest disagreement > false agreement
  - State limitations plainly

context:
  location: Canberra AU
  timezone: Australia/Sydney
  models: [claude-sonnet-4-20250514, claude-haiku]

capabilities: [email, calendar, goals, shopping, reminders]
commands: [help, cancel, status, goals, logs]

limits:
  forbidden: [arbitrary code, system dirs, credentials]
  report: [degradation, rate limits, timeouts]
```

**Pros:** Very structured, easy to parse programmatically
**Cons:** Less natural for personality nuance, harder to express voice examples

### Option 3: JSON

```json
{
  "identity": {"name": "Remy", "owner": "Dale", "nature": "AI agent"},
  "voice": {"tone": "warm, direct", "wit": "dry", "locale": "en-AU"},
  "principles": ["Memory is core", "Brevity is respect"],
  ...
}
```

**Pros:** Minimal whitespace, highly structured
**Cons:** Poor readability, quotes add overhead, hard to maintain personality nuance

### Option 4: Custom DSL / Shorthand

```
@remy owner=Dale nature=ai-agent
voice: warm+direct wit=dry locale=en-AU
principles: memory-core, brevity, honest-disagreement
limits.forbidden: code,sysdirs,creds
```

**Pros:** Maximum compression
**Cons:** Learning curve, brittle, hard to extend, Claude may misinterpret

### Recommendation: Compressed Markdown

1. **Claude understands Markdown natively** — no parsing overhead or interpretation risk
2. **Personality nuance preserved** — natural language for voice/tone
3. **Human-maintainable** — users can edit without learning a schema
4. **Good compression** — 40–50% reduction achievable
5. **Graceful degradation** — if compression fails, original still works

---

## Acceptance Criteria

### 1. Create `SOUL.compact.md` format specification
Document the compressed format with guidelines:
- Single-line sections where possible
- Bullet points instead of paragraphs
- Remove redundant headers and dividers
- Abbreviate common patterns (e.g., "No:" instead of "What the Agent CANNOT Do")

### 2. Provide migration script
`scripts/compress_soul.py` that:
- Reads existing `SOUL.md`
- Outputs compressed version to `SOUL.compact.md`
- Reports token count before/after
- Validates key sections are preserved

### 3. Update `SOUL.example.md` with compact version
Provide both formats:
- `config/SOUL.example.md` — full verbose version (for reference)
- `config/SOUL.compact.example.md` — compressed version (recommended)

### 4. Add token counting utility
`remy/utils/tokens.py`:
```python
def count_tokens(text: str, model: str = "claude-sonnet-4-20250514") -> int:
    """Estimate token count for text."""
```

### 5. Config option for soul format
`settings.soul_compact: bool = True` — when True, prefer `SOUL.compact.md` if it exists.

### 6. Logging of system prompt size
Log system prompt token count at DEBUG level on each API call:
```
DEBUG: System prompt: 847 tokens (soul: 412, memory: 435)
```

---

## Implementation

**New files:**
- `config/SOUL.compact.example.md` — compressed template
- `scripts/compress_soul.py` — migration utility
- `remy/utils/tokens.py` — token counting

**Modified files:**
- `remy/config.py` — add `soul_compact` setting, prefer compact if exists
- `remy/memory/injector.py` — log token breakdown
- `remy/ai/claude_client.py` — pass through token counts for logging

### Token estimation approach

Use `anthropic.count_tokens()` if available, otherwise estimate:
- ~4 characters per token for English prose
- ~3.5 characters per token for structured/code content

---

## Test Cases

| Scenario | Expected |
|---|---|
| Compress verbose SOUL.md | Output is 40–50% smaller in tokens |
| Compressed soul loads correctly | `settings.soul_md` returns compact content |
| Personality preserved | Claude responses maintain same voice/tone |
| Missing compact file | Falls back to full SOUL.md |
| Token logging enabled | DEBUG logs show soul/memory breakdown |
| Invalid compact format | Validation warns, falls back to full |

---

## Out of Scope

- Automatic compression via LLM (too risky for personality drift)
- Runtime soul modification (soul is static per session)
- Per-message soul variation (same soul for all messages)
- Binary/encoded formats (must remain human-readable)

---

## Notes on JSON

JSON was considered but rejected for soul compression because:

1. **Quote overhead** — Every key and string value requires quotes, adding ~15% overhead
2. **No comments** — Can't annotate sections for maintainability
3. **Personality loss** — Hard to express nuanced voice in key-value pairs
4. **Escape hell** — Markdown formatting in JSON requires escaping
5. **Claude preference** — Claude handles Markdown more naturally than JSON for behavioural instructions

JSON remains appropriate for structured data (facts, goals, API responses) but not for personality/behavioural prompts where natural language nuance matters.
