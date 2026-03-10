# User Story: Fix primp Impersonation Header Warning

**Status:** ✅ Done

## Summary

As a developer, I want the noisy `primp.impersonate: Impersonate 'chrome_114' does not exist, using 'random'` warning silenced so that production logs are not polluted with every web search call.

---

## Background

`remy/web/search.py` uses the `ddgs` library (DuckDuckGo search, `ddgs>=9.0`) which internally uses `primp` for HTTP impersonation. `primp` accepts a browser impersonation target string such as `"chrome_114"`. In the current version of `primp`, `chrome_114` is no longer a valid target and falls back to `"random"`, emitting a WARNING on every request:

```
[WARNING] primp.impersonate: Impersonate 'chrome_114' does not exist, using 'random'
```

This fires on every `/search`, `/research`, `/price-check`, and any other tool that calls `web_search()`. The `"random"` fallback works fine — the warning is noise, not a functional error.

Related to Bug 16 in `BUGS.md`.

---

## Acceptance Criteria

1. **Warning suppressed or eliminated.** The `primp.impersonate` WARNING no longer appears in production logs during normal web search usage.
2. **Search functionality unchanged.** `web_search()` returns results with the same quality as before.
3. **No new dependency.** The fix uses only what is already available (`ddgs`, `primp`, standard `logging`, or `warnings` modules).
4. **Upgrade is pinned if used.** If the fix involves upgrading `ddgs`, the new minimum version is documented in `requirements.txt` with a comment.

---

## Implementation

**Files:** `remy/web/search.py`, `requirements.txt` (if pinning a newer `ddgs` version).

### Option A — Upgrade ddgs (preferred if a fixed version exists)

Check whether a newer `ddgs` release uses a valid impersonation target. If so, bump the minimum version:

```text
# requirements.txt
ddgs>=9.2  # >=9.2 fixes primp chrome_114 impersonation warning
```

Verify by running a search and confirming the warning is gone.

### Option B — Suppress via warnings filter (fallback)

If the upstream fix is not yet available, suppress the specific warning using Python's `warnings` module in `search.py`:

```python
import warnings

def _sync() -> list[dict]:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Impersonate.*does not exist")
        from ddgs import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
```

### Option C — Pass a valid impersonation target to DDGS

If `DDGS` accepts an `impersonate` constructor argument, pass a currently-valid string:

```python
with DDGS(impersonate="chrome_124") as ddgs:
    ...
```

Check the `ddgs` API for the current list of valid targets before committing to a specific string.

### Notes

- Try Option A first — it's zero code change and fixes the root cause.
- Option B is the most defensive; it will survive future version changes.
- Option C couples Remy to a specific impersonation string that may itself go stale.
- The warning comes from `primp`'s own logger, not Python's `warnings` module — if Option B doesn't work, filter by logger name instead: `logging.getLogger("primp").setLevel(logging.ERROR)` at the top of `search.py`.

---

## Test Cases

| Scenario | Expected |
|---|---|
| `web_search("test")` called once | No `[WARNING] primp.impersonate` in logs |
| `web_search()` called 10 times in succession | No repeated warnings |
| Search returns results normally | Results list is non-empty for a known query |
| ddgs unavailable (ImportError) | Existing graceful fallback unchanged |

---

## Out of Scope

- Replacing `ddgs` with a different search library — not warranted for a warning.
- Implementing HTTP impersonation at the Remy level — `ddgs`/`primp` handles this adequately.
