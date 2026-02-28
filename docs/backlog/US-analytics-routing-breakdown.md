# User Story: /routing — Routing Efficiency & Classifier Cost Breakdown

⬜ Backlog

## Summary

As Dale, I want a `/routing` command that shows how my messages are being categorised and routed across models — including classifier overhead, fallback rates, and per-category token averages — so that I can tune the orchestration logic if something looks wrong.

---

## Background

The `ModelRouter` makes routing decisions based on the `MessageClassifier` output and approximate token count. These decisions directly affect cost and latency, but there is currently no visibility into them:

- Which categories are most common? Are most messages going to "routine" (cheap) or "reasoning" (expensive)?
- How much does classification itself cost? The classifier is a Claude `complete()` call on every message — at high volume this overhead matters.
- What percentage of calls fall back to Ollama? A high fallback rate signals a reliability problem.
- Are the token-threshold routing rules working as intended? (e.g., long "summarization" tasks going to Mistral Large rather than Claude Haiku)

**Covers:** ANA-007 (routing breakdown command), ANA-011 (classifier cost visibility), ANA-012 (per-category token benchmarking).

**Depends on:** `US-analytics-call-log.md` (requires `api_calls` table with `category`, `call_site`, and token counts).

---

## Acceptance Criteria

1. **`/routing` command registered.** Accepts optional period: `/routing`, `/routing 7d`. Default: last 30 days.

2. **Category breakdown table.** For each observed routing category (`routine`, `summarization`, `reasoning`, `coding`, `safety`, `persona`, `unknown`), shows:
   - Call count
   - Primary provider/model chosen
   - Average input + output tokens per call
   - Estimated average cost per call

3. **Fallback rate.** Shows count and percentage of calls where Ollama was used as fallback (i.e., `fallback=1` in `api_calls`). If fallback rate > 5%, a warning marker is shown.

4. **Classifier overhead section.** Shows separately:
   - Total classifier calls in period
   - Total tokens consumed by classifier (input + output)
   - Estimated cost of classification alone
   - Classifier cost as a percentage of total spend
   - If classifier overhead > 10% of total spend: a note suggesting lighter-weight classification heuristics

5. **Proactive and background calls shown separately.** `call_site="proactive"` and `call_site="background"` are shown as their own rows so their costs are visible and not diluting the user-initiated routing stats.

6. **Data sourced from `api_calls` table only.** No JSONL reads.

7. **Period header** shows date range, total calls, total tokens, total estimated cost (consistent with `/costs`).

---

## Implementation

**Files to create/modify:**
- `remy/analytics/routing.py` — new `RoutingAnalyzer` class
- `remy/bot/handlers.py` — register `/routing` command handler

**Core query — per-category aggregation:**

```sql
SELECT
    category,
    call_site,
    provider,
    model,
    COUNT(*)                              AS calls,
    SUM(input_tokens + output_tokens)     AS total_tokens,
    AVG(input_tokens + output_tokens)     AS avg_tokens,
    SUM(fallback)                         AS fallback_calls,
    AVG(latency_ms)                       AS avg_latency_ms
FROM api_calls
WHERE user_id = ?
  AND timestamp >= ?
  AND timestamp < ?
GROUP BY category, call_site, provider, model
ORDER BY calls DESC
```

**Classifier overhead query:**

```sql
SELECT
    COUNT(*)                              AS calls,
    SUM(input_tokens)                     AS input_tokens,
    SUM(output_tokens)                    AS output_tokens
FROM api_calls
WHERE user_id = ?
  AND call_site = 'classifier'
  AND timestamp >= ?
  AND timestamp < ?
```

**Sample output format:**

```
🔀 *Routing Breakdown — Last 30 days*
399 total calls · 5.4M tokens · ~$28.37 estimated

📊 *By Category*
routine         ×112  →  mistral-medium-3     avg 4.2K tok  ~$0.002/call
summarization   ×87   →  claude-sonnet-4-6    avg 9.8K tok  ~$0.09/call
reasoning       ×34   →  claude-sonnet-4-6    avg 12.1K tok ~$0.12/call
coding          ×28   →  claude-sonnet-4-6    avg 8.3K tok  ~$0.08/call
persona         ×19   →  moonshot-v1-8k       avg 3.1K tok  ~$0.001/call
safety          ×6    →  claude-sonnet-4-6    avg 5.5K tok  ~$0.05/call

🤖 *Other Call Sites*
proactive       ×18   →  claude-sonnet-4-6    avg 7.2K tok  ~$0.07/call
background      ×9    →  claude-sonnet-4-6    avg 3.8K tok  ~$0.04/call

⚡ *Classifier Overhead*
95 calls · 210K input + 12K output tokens
Estimated cost: ~$0.81  (2.9% of total spend)

⚠️ *Fallback Rate*
3 calls fell back to Ollama (0.8%) — within normal range
```

### Notes

- The "primary provider/model" shown per category is the most common `provider:model` combination for that category in the period, not a static mapping. This reflects what actually happened, which may differ from the intended routing table if fallbacks occurred.
- Average cost per call is computed using `estimate_cost()` from `US-analytics-costs-command.md`'s price table. Extract `remy/analytics/prices.py` as a shared module between both commands.
- If multiple models served the same category (e.g., routing changed mid-period), show the top model only and add `+N more` in parentheses.
- The classifier overhead warning threshold (10%) is a constant at the top of `routing.py` — easy to adjust.

---

## Test Cases

| Scenario | Expected |
|---|---|
| `/routing` with varied categories | All observed categories shown with correct counts |
| Period with zero fallbacks | Fallback section shows 0 calls, no warning |
| Fallback rate > 5% | Warning marker shown next to fallback count |
| Classifier overhead > 10% of spend | Note shown suggesting lighter-weight heuristics |
| Only one category in period | Single-row table, no crash |
| No calls in `api_calls` for period | Empty state message |
| Proactive pipeline calls present | Shown in "Other Call Sites" section |
| Multiple models served same category | Top model shown, `+N more` noted |

---

## Out of Scope

- A/B testing or automatic routing rule adjustment based on analytics data.
- Per-model latency percentiles (p50/p95) — deferred to a future story.
- Routing rule suggestions or automated tuning.
- Historical trends chart (text-only output is sufficient for now).
