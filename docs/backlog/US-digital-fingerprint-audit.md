# ✅ Done

# User Story: Digital Fingerprint Privacy Audit

## Summary

As a user, I want Remy to help me audit my digital footprint — data broker presence,
account exposure, and privacy hygiene — through a guided conversation, without Remy
needing to access or scrape any external services directly.

---

## Background

Phase 4.3 in the roadmap identified a "digital fingerprint audit" as a Could Have feature.
The insight from the TODO is that **no new code is needed** — the existing `/research`
command and Board of Directors can already do this work through prompting. This story
captures the implementation as a deliberate prompt/UX pattern rather than new tooling.

---

## Acceptance Criteria

1. **`/privacy-audit` command** (or natural language equivalent) triggers a structured
   multi-step conversation:
   - Step 1: Remy asks for names, email addresses, or usernames to check.
   - Step 2: Remy uses `/research` to search data broker sites and known breach databases.
   - Step 3: Board of Directors synthesises findings into a prioritised action plan.
2. **No external API required.** Uses DuckDuckGo search (already available) only.
3. **Results are sensitive — not stored as facts or in conversation history** beyond the
   active session unless the user explicitly asks.
4. **Graceful scope-setting.** Remy is upfront that results are based on public web search
   and are not exhaustive.

---

## Implementation

**No new Python files.** Implementation is a prompt pattern + slash command handler.

**`bot/handlers.py`:** Add `/privacy-audit` as a special-cased slash command that injects
a structured system prompt addendum directing Claude to follow the multi-step audit flow.

**Suggested system prompt addendum:**

```
The user has requested a privacy audit. Guide them through the following steps:
1. Ask which names, email addresses, or usernames to check.
2. Use web_search to look up each on data broker sites and HaveIBeenPwned.
3. Summarise exposure level (low/medium/high) per identity with sources.
4. Offer a prioritised action list (opt-out links, password changes, 2FA gaps).
Do not store the user's personal identifiers as memory facts unless they ask.
```

---

## Test Cases

| Scenario                    | Expected                                            |
| --------------------------- | --------------------------------------------------- |
| User sends `/privacy-audit` | Remy prompts for names/emails to check              |
| User provides email address | Remy searches for breaches and broker listings      |
| No results found            | Remy reports "no known exposure" with caveats       |
| User asks to save results   | Remy offers to append to a file, not store as facts |

---

## Out of Scope

- Automated monitoring or alerts for new breaches (requires external subscription)
- Direct API calls to HaveIBeenPwned (requires API key — not in scope)
- Storing audit results in the memory system without explicit user consent
