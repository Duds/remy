# User Story: Email Triage Sub-Agent

**Status:** ⬜ Backlog

## Summary
As Dale, I want Remy to autonomously triage unlabelled emails in the background so that I can say "triage the inbox" and walk away — without Remy blocking a conversation thread to classify emails one batch at a time.

---

## Background

Email labelling is currently done inline during conversation, with Remy fetching 20 unlabelled emails at a time, classifying each against the taxonomy stored in memory, then applying labels in parallel. This works but is slow (each batch requires a full round-trip through the primary agent) and blocks the conversation while running.

The label taxonomy is well-established and stored in memory (fact id 52). The classification logic is stable and consistent enough to delegate to a dedicated worker.

This story introduces a background `email_triage_agent` that can be dispatched as a job, runs autonomously until the unlabelled queue is empty, then reports a summary.

Related: `US-background-task-runner.md`, `US-persistent-job-tracking.md`.

---

## Acceptance Criteria

1. **Trigger.** User can say "triage the inbox" (or similar) and Remy dispatches the job without blocking the conversation.
2. **Autonomous loop.** The agent fetches batches of unlabelled emails, classifies all emails in a batch in a single LLM call, applies labels in parallel, and loops until no unlabelled emails remain.
3. **Taxonomy-aware.** Classification uses the full label taxonomy from memory (fact id 52), including correct label IDs for each category.
4. **Flagging unknowns.** Emails that cannot be confidently classified are collected and reported to Dale at the end rather than silently skipped or mislabelled.
5. **Summary on completion.** When done, the agent sends a Telegram message: total processed, breakdown by label category, and any emails requiring manual review.
6. **Idempotent.** Running the agent twice does not double-label already-labelled emails.
7. **Regression.** Existing inline triage behaviour (when done conversationally) is unchanged.

---

## Implementation

**Files:**
- `remy/agents/email_triage_agent.py` — new worker agent
- `remy/tools/gmail_tools.py` — minor: expose batch classify helper if needed
- `remy/handlers/primary_chat.py` — detect triage intent and dispatch job
- `remy/jobs/` — register as a dispatchable background job

### Approach

The agent runs as a background job (via the existing job runner). Its loop:

```python
async def run_email_triage_agent():
    while True:
        emails = await fetch_unlabelled_batch(max=20)
        if not emails:
            break

        # Single LLM call to classify the whole batch
        classifications = await classify_batch(emails, taxonomy=LABEL_TAXONOMY)

        # Apply labels in parallel
        await asyncio.gather(*[
            apply_labels(email_id, label_ids, archive=True)
            for email_id, label_ids in classifications.items()
            if label_ids  # skip unknowns
        ])

        unknowns.extend([e for e in emails if not classifications.get(e.id)])

    await send_summary(processed=total, by_category=counts, review=unknowns)
```

**Classification prompt** should include:
- The full taxonomy (label name → label ID mapping)
- All email subjects + senders (no bodies needed for most)
- Instruction to return a JSON map of `{message_id: [label_ids]}`
- A special `"unknown"` value for emails that don't fit

**Taxonomy source:** Load from memory fact id 52 at job start, so it stays current without code changes.

### Notes
- Fetch query: `has:nouserlabels -in:sent -in:drafts -in:spam -in:trash`
- Batch size of 20 is the Gmail API search max — keep it.
- Rate limiting: Gmail allows ~250 label operations/second. Parallel apply is safe.
- Consider a dry-run mode (`triage inbox --dry-run`) that logs classifications without applying labels, for taxonomy validation.
- Depends on `US-persistent-job-tracking.md` for job status and summary delivery.

---

## Test Cases

| Scenario | Expected |
|---|---|
| Empty queue | Agent exits immediately, reports "0 emails processed" |
| Mixed batch (known + unknown senders) | Known emails labelled correctly; unknowns collected for review |
| Already-labelled email in results | `has:nouserlabels` filter prevents re-fetch; idempotent |
| Taxonomy updated in memory mid-run | Agent loaded taxonomy at job start — current run uses snapshot; next run picks up changes |
| Job dispatched twice simultaneously | Second job should detect first is running and decline gracefully |

---

## Out of Scope

- Reading email bodies for classification (subject + sender is sufficient for the vast majority; body-reading can be a follow-up enhancement)
- Auto-unsubscribing from mailing lists (separate story)
- Modifying the taxonomy itself (that's a memory management concern)
- Real-time streaming progress updates (summary on completion is sufficient for now)
