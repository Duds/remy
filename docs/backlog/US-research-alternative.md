# User Story: Research Platform Alternatives

## Summary
As a user, I want to ask Remy "what's a good alternative to X?" for any platform or service
and receive a structured comparison — without needing a dedicated slash command.

---

## Background

Phase 4.4 in the roadmap named a `/research-alternative <platform>` command, but the
conclusion was that `/research` already covers this use case. This story captures that
conclusion and defines what a good response looks like so Claude's system prompt or tool
description can be tuned if the quality falls short.

**Verdict:** No new command or tool needed. This is a prompt quality / UX expectation story.

---

## Acceptance Criteria

1. **Natural language works without a slash command.** "What's a good alternative to
   Notion for ADHD users?" triggers a web search + synthesis without needing `/research`.
2. **Results include:** direct alternatives, key differentiators, pricing tier, privacy
   stance (if relevant), and a recommended pick with rationale.
3. **Response is structured** — not a wall of text. Uses headers or a comparison table.
4. **If no good web results are found**, Remy says so and offers to refine the query.

---

## Implementation

**No new code.** Tune the `web_research` tool description in `tool_registry.py` to include
an example of the alternative-finding use case so Claude reliably produces structured
comparisons.

If response quality is consistently poor, add a `/research-alternative` shortcut that
injects a system prompt addendum:

```
The user wants platform alternatives. For each alternative found:
- Name, URL, pricing summary
- Key differentiator vs the original platform
- Privacy/open-source status if relevant
- A recommended pick with one-line rationale
Format as a markdown table followed by a recommendation paragraph.
```

---

## Test Cases

| Scenario | Expected |
|---|---|
| "What's a good Notion alternative?" | Structured table of alternatives + recommendation |
| "Alternative to Gmail that respects privacy?" | Privacy-focused options listed |
| "Replace Slack for a small team" | Pricing-aware comparison |
| Obscure platform with no results | Clear "I couldn't find enough data" response |

---

## Out of Scope

- Saving alternatives as bookmarks automatically (user can ask explicitly)
- Price tracking or availability monitoring
- Any new slash command unless response quality proves consistently poor
