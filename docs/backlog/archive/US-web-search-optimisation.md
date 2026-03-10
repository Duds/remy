# User Story: Optimise Web Search to Reduce Round-Trip Latency

**Status:** ✅ Done

## Summary

As a user, I want Remy to answer research questions without chaining 8+ sequential web searches so that replies arrive in seconds instead of minutes.

---

## Background

Logs from 03/03/2026 show Remy issuing multiple sequential `web_search` calls per turn (e.g. 03:50–03:53: 8+ searches for "Telegram Bot API allowed emoji reactions"). Each search hits several engines (Wikipedia, Grokipedia, Mojeek, DuckDuckGo, Yandex, Google, Brave). Total latency for that turn was ~93 s.

The model appears to refine queries iteratively instead of searching once and deciding. There is no caching of search results, so repeated or similar queries hit the network every time.

Related: `remy/ai/tools/` (web_search tool), primp integration, `remy/ai/claude_client.py`.

---

## Acceptance Criteria

1. **Per-turn search limit.** A configurable cap (e.g. `WEB_SEARCH_MAX_PER_TURN=3`) limits how many `web_search` invocations can run in a single user turn. When the cap is reached, the model must synthesise from results already retrieved.
2. **Search result caching (optional).** For identical or near-identical queries within a session or short TTL, return cached results instead of hitting the network.
3. **Prompt guidance.** Tool description or system prompt encourages "search once, then decide" — run one or two well-formed searches before synthesising, rather than iteratively refining.
4. **Graceful degradation.** When the cap is hit, the model responds with available results and may suggest the user rephrase if more specific research is needed.
5. **Telemetry.** Log `web_search_cap_hit` when the limit is reached.

---

## Implementation

**Files:** `remy/config.py`, `remy/ai/tools/` (web_search), `remy/ai/tools/registry.py`, tool schema in `schemas.py`.

- Add `web_search_max_per_turn: int = 3` to `Settings`.
- In the tool dispatch loop (or wrapper around `web_search`), track `web_search` calls per turn and reject with a structured error when cap is exceeded. The error message should instruct the model to use existing results.
- Optionally: add an in-memory cache keyed by normalised query string, TTL e.g. 5 minutes.
- Update `web_search` tool description to mention the cap and encourage efficient query design.

### Notes

- The cap could be enforced in `ToolRegistry.dispatch()` by counting invocations per turn, or in a wrapper around the primp/search implementation.
- Cache key normalisation: lowercase, strip extra whitespace, maybe truncate very long queries.
- Consider whether the cap should apply per tool type (only web_search) or globally — this story focuses on web_search.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Single web_search per turn | Works as today |
| 3 web_search calls, cap=3 | All execute; 4th returns "cap reached" message to model |
| Identical query within TTL (if cache) | Cache hit; no network call |
| Model receives cap message | Synthesises reply from prior results |

---

## Out of Scope

- Changing which search engines are used.
- Parallelising multiple searches (separate story).
- General tool-call caps (see US-cap-tool-iterations-per-turn).
