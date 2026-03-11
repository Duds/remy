# User Story: Email Triage Sub-Agent

**Status:** ✅ Done (2026-03-11 — email_triage_agent, triage_inbox tool, background job)

## Summary
As Dale, I want Remy to autonomously triage unlabelled emails in the background so that I can say "triage the inbox" and walk away — without Remy blocking a conversation thread to classify emails one batch at a time.

---

## Background

Email labelling was done inline; this story adds a background `email_triage_agent` dispatched as a job, using taxonomy from memory (knowledge id 52), classifying batches with a single LLM call, applying labels in parallel, and sending a summary when done.

---

## Acceptance Criteria (summary)

- Trigger: user says "triage the inbox" → job dispatched without blocking.
- Autonomous loop: fetch unlabelled batches, classify with LLM, apply labels, until empty.
- Taxonomy from memory (fact id 52); unknowns reported at end; idempotent.

---

## Files

`remy/agents/email_triage_agent.py`, `remy/ai/tools/schemas.py`, `remy/ai/tools/email.py`, `remy/ai/tools/registry.py`.
