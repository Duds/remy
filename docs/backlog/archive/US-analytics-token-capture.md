# User Story: Per-Call Token Capture from Stream APIs

✅ Done

## Summary

As Remy, I want to capture input and output token counts from the live stream response of every Claude, Mistral, and Moonshot API call so that I have accurate per-call cost data without polling a separate billing API.

---

## Background

All three services expose token counts inside the streaming response itself — no separate API call is required. Currently none of this data is captured:

- `ClaudeClient` streams text deltas only; the `message_start` and `message_delta` events that carry token counts are discarded.
- `MistralClient` discards the final SSE chunk (which includes `usage`) once it sees `[DONE]`.
- `MoonshotClient` does not set `stream_options: {"include_usage": true}`, so no usage chunk is emitted at all.

Without per-call token counts we cannot compute cost estimates, compare routing efficiency, or detect regressions in token consumption over time. This story provides the raw capture layer; `US-analytics-call-log.md` covers persistence.

**Covers:** ANA-001 (Anthropic), ANA-002 (Mistral), ANA-003 (Moonshot).

---

## Acceptance Criteria

1. **Shared `TokenUsage` model.** A `TokenUsage` dataclass (or Pydantic model) is added to `remy/models.py` with fields: `input_tokens: int`, `output_tokens: int`, `cache_creation_tokens: int = 0`, `cache_read_tokens: int = 0`. Mistral and Moonshot set cache fields to `0`.

2. **Anthropic — `stream_message()`.** Parses `message_start.message.usage` for `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`. Parses `message_delta.usage.output_tokens` for final output count. Returns `TokenUsage` alongside the stream (e.g., via a tuple or a callback).

3. **Anthropic — `stream_with_tools()`.** Same parsing applied across all iterations of the tool-use loop. `TokenUsage` values are accumulated (summed) across iterations so callers get the total for the full agentic turn.

4. **Mistral — `stream_chat()`.** Reads `usage.prompt_tokens` and `usage.completion_tokens` from the last data chunk before `[DONE]`. If no `usage` key is present (error path), defaults to `TokenUsage(0, 0)` and logs a warning at DEBUG level.

5. **Moonshot — `stream_chat()`.** Adds `"stream_options": {"include_usage": True}` to every request payload. Reads the extra chunk emitted after `[DONE]` containing `usage.prompt_tokens` and `usage.completion_tokens`. If the extra chunk is absent or malformed, defaults to `TokenUsage(0, 0)` and logs a warning.

6. **Ollama fallback.** `OllamaClient` returns `TokenUsage(0, 0)` — no token counting required for local models.

7. **No additional API calls.** All token data sourced exclusively from the live stream events. No polling of billing or usage endpoints in this story.

8. **Callers not broken.** `ModelRouter` and all call sites continue to work unchanged — token capture is additive and does not alter the text yield behaviour of any client.

---

## Implementation

**Files to modify:**
- `remy/models.py` — add `TokenUsage`
- `remy/ai/claude_client.py` — parse stream events
- `remy/ai/mistral_client.py` — parse final chunk
- `remy/ai/moonshot_client.py` — add `stream_options`, parse extra chunk
- `remy/ai/ollama_client.py` — add stub returning `TokenUsage(0, 0)`

**`TokenUsage` model (`remy/models.py`):**

```python
class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_tokens=self.cache_creation_tokens + other.cache_creation_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
        )
```

**Anthropic stream event parsing (`claude_client.py`):**

The raw event loop in `stream_with_tools()` already iterates `async for event in stream`. Add:

```python
# In stream_message() — after the stream context manager closes, use get_final_message():
final_msg = await stream.get_final_message()
usage = TokenUsage(
    input_tokens=final_msg.usage.input_tokens,
    output_tokens=final_msg.usage.output_tokens,
    cache_creation_tokens=getattr(final_msg.usage, "cache_creation_input_tokens", 0),
    cache_read_tokens=getattr(final_msg.usage, "cache_read_input_tokens", 0),
)
```

For `stream_with_tools()`, call `get_final_message()` already happens per-iteration — accumulate `TokenUsage` across iterations using `__add__`.

**Mistral final chunk parsing:**

```python
# In the SSE parse loop, before the `[DONE]` check:
if data_str == "[DONE]":
    break
data = json.loads(data_str)
if "usage" in data:
    usage = TokenUsage(
        input_tokens=data["usage"].get("prompt_tokens", 0),
        output_tokens=data["usage"].get("completion_tokens", 0),
    )
```

**Moonshot stream options + extra chunk:**

```python
payload["stream_options"] = {"include_usage": True}
# After [DONE], read one more line for the usage chunk
```

**Returning `TokenUsage` to callers.** The cleanest approach is to pass a mutable container:

```python
async def stream_chat(self, messages, ..., usage_out: TokenUsage | None = None)
# caller passes usage_out=TokenUsage() and reads it after the stream is consumed
```

Alternatively, `ModelRouter._stream_with_fallback()` can own a `TokenUsage` instance and expose it via a property (similar to `last_model`).

### Notes
- `stream_with_tools()` in `claude_client.py` already calls `get_final_message()` per-iteration at line 204. This is the right hook — do not add a second `get_final_message()` call.
- This story is a prerequisite for `US-analytics-call-log.md`. The call log cannot be written without `TokenUsage` data.
- Moonshot's `stream_options` parameter was confirmed against the OpenAI-compatible API; test with `moonshot-v1-8k` first before enabling on `kimi-k2-thinking` which may behave differently.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Claude `stream_message()` completes normally | `TokenUsage` has non-zero `input_tokens` and `output_tokens` |
| Claude `stream_with_tools()` with 2 tool iterations | `TokenUsage` is sum of both iterations |
| Claude with cache hit | `cache_read_tokens > 0`, `cache_creation_tokens == 0` |
| Mistral stream completes normally | `TokenUsage.input_tokens == prompt_tokens` from final chunk |
| Mistral stream — error response (non-200) | Returns `TokenUsage(0, 0)`, logs warning |
| Mistral final chunk has no `usage` key | Returns `TokenUsage(0, 0)`, logs warning |
| Moonshot stream with `include_usage: true` | Extra chunk after `[DONE]` parsed correctly |
| Moonshot stream — extra chunk absent | Returns `TokenUsage(0, 0)`, logs warning |
| Ollama fallback invoked | Returns `TokenUsage(0, 0)` |
| Existing text streaming behaviour | Unchanged — all text chunks still yielded in order |

---

## Out of Scope

- Time-to-first-token measurement (deferred to `US-analytics-call-log.md` stretch goal).
- Cost calculation from token counts (handled in `US-analytics-costs-command.md`).
- Persisting `TokenUsage` to the database (handled in `US-analytics-call-log.md`).
- Mistral per-model cache breakdowns (Mistral does not expose cache token fields).
