"""
Email triage sub-agent — background job that classifies and labels unlabelled emails.

Fetches batches of unlabelled emails, classifies with LLM using taxonomy from memory,
applies labels in parallel, and sends a summary when done (US-email-triage-subagent).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..google.gmail import GmailClient
    from ..memory.database import DatabaseManager

logger = logging.getLogger(__name__)

_TRIAGE_QUERY = "has:nouserlabels -in:sent -in:drafts -in:spam -in:trash"
_BATCH_SIZE = 20
_TAXONOMY_KNOWLEDGE_ID = 52


async def load_taxonomy(
    user_id: int,
    db: "DatabaseManager",
) -> dict[str, str]:
    """
    Load label name → label ID mapping from knowledge table (e.g. fact id 52).
    Returns a dict like {"Work": "Label_123", "Personal": "Label_456"}.
    """
    async with db.get_connection() as conn:
        cursor = await conn.execute(
            "SELECT content, metadata FROM knowledge WHERE id=? AND user_id=?",
            (_TAXONOMY_KNOWLEDGE_ID, user_id),
        )
        row = await cursor.fetchone()
    if not row:
        return {}
    content = row[0] or ""
    metadata = row[1] or "{}"
    try:
        meta = json.loads(metadata) if isinstance(metadata, str) else metadata
        if isinstance(meta.get("label_taxonomy"), dict):
            return meta["label_taxonomy"]
        if isinstance(meta.get("labels"), dict):
            return meta["labels"]
    except (json.JSONDecodeError, TypeError):
        pass
    # Try to parse content as JSON (e.g. {"Work": "Label_123"})
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return {}


async def run_email_triage(
    user_id: int,
    gmail: "GmailClient",
    db: "DatabaseManager",
    claude_client,
) -> str:
    """
    Run the email triage loop: fetch unlabelled batches, classify with LLM,
    apply labels, until queue is empty. Returns a summary string for the user.
    """
    taxonomy = await load_taxonomy(user_id, db)
    if not taxonomy:
        return (
            "Email triage skipped: no label taxonomy found in memory (knowledge id 52). "
            "Store a fact with label name → label ID mapping to enable triage."
        )

    total_processed = 0
    by_label: dict[str, int] = {}
    unknowns: list[dict] = []
    errors: list[str] = []

    while True:
        try:
            emails = await gmail.search(
                _TRIAGE_QUERY,
                max_results=_BATCH_SIZE,
                include_body=False,
                label_ids=None,
            )
        except Exception as e:
            logger.exception("Gmail search failed during triage: %s", e)
            errors.append(str(e))
            break
        if not emails:
            break

        # Build batch for classification: id, subject, from
        batch = [
            {"id": e["id"], "subject": e.get("subject", ""), "from": e.get("from_addr", "")}
            for e in emails
        ]
        try:
            classifications = await _classify_batch(
                batch,
                taxonomy,
                claude_client,
            )
        except Exception as e:
            logger.exception("Classification failed: %s", e)
            errors.append(f"Classification: {e}")
            break

        # Apply labels in parallel (one task per message)
        apply_tasks = []
        for msg_id, label_ids in classifications.items():
            if not label_ids or "unknown" in label_ids:
                em = next((e for e in emails if e["id"] == msg_id), {})
                unknowns.append(em)
                continue
            valid_ids = [l for l in label_ids if l in taxonomy.values()]
            if not valid_ids:
                em = next((e for e in emails if e["id"] == msg_id), {})
                unknowns.append(em)
                continue
            apply_tasks.append(
                gmail.modify_labels(
                    [msg_id],
                    add_label_ids=valid_ids,
                    remove_label_ids=["INBOX"],
                )
            )
            total_processed += 1
            for lbl in valid_ids:
                by_label[lbl] = by_label.get(lbl, 0) + 1

        if apply_tasks:
            results = await asyncio.gather(*apply_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    errors.append(str(r))

    # Build summary
    lines = [f"**Email triage complete** — {total_processed} message(s) processed."]
    if by_label:
        lines.append("By label:")
        for lbl_id, count in sorted(by_label.items(), key=lambda x: -x[1]):
            lines.append(f"  • {count}")
    if unknowns:
        lines.append(f"\n{len(unknowns)} email(s) need manual review (no confident label).")
    if errors:
        lines.append(f"\nErrors: {'; '.join(errors[:3])}")
    return "\n".join(lines)


async def _classify_batch(
    batch: list[dict],
    taxonomy: dict[str, str],
    claude_client,
) -> dict[str, list[str]]:
    """
    Single LLM call to classify the batch. Returns {message_id: [label_id]} or
    {message_id: ["unknown"]}.
    """
    taxonomy_str = json.dumps(taxonomy, indent=2)
    batch_str = "\n".join(
        f"id={e['id']} from={e.get('from', '')} subject={e.get('subject', '')}"
        for e in batch
    )
    prompt = f"""You classify emails into the user's Gmail label taxonomy. Return ONLY a JSON object mapping each message id to a list of label IDs to apply (use the exact IDs from the taxonomy). If an email does not fit any category, use "unknown" as the value.

Taxonomy (label name → label ID):
{taxonomy_str}

Emails (one per line):
{batch_str}

Return JSON only, e.g. {{"msg_id_1": ["Label_123"], "msg_id_2": ["unknown"]}}."""

    try:
        raw = await claude_client.complete(
            messages=[{"role": "user", "content": prompt}],
            system="You return only valid JSON. No commentary.",
            max_tokens=1024,
        )
    except Exception as e:
        logger.warning("Claude complete failed in triage classify: %s", e)
        return {item["id"]: ["unknown"] for item in batch}

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            return {e["id"]: ["unknown"] for e in batch}
        out = {}
        for e in batch:
            msg_id = e["id"]
            val = data.get(msg_id, data.get(str(msg_id), ["unknown"]))
            if isinstance(val, list):
                out[msg_id] = val
            else:
                out[msg_id] = [val] if val else ["unknown"]
        return out
    except json.JSONDecodeError:
        return {e["id"]: ["unknown"] for e in batch}
