"""Plan tracking tool executors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)


async def exec_create_plan(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Create a new multi-step plan."""
    if registry._plan_store is None:
        return "Plan tracking not available."

    title = inp.get("title", "").strip()
    description = inp.get("description", "").strip() or None
    steps = inp.get("steps", [])

    if not title:
        return "Please provide a title for the plan."
    if not steps:
        return "Please provide at least one step for the plan."

    try:
        plan_id = await registry._plan_store.create_plan(
            user_id, title, description, steps
        )
    except Exception as e:
        return f"Could not create plan: {e}"

    step_list = "\n".join(f"  {i}. {s}" for i, s in enumerate(steps, 1))
    return (
        f"✅ Plan created (ID {plan_id}): {title}\n\n"
        f"Steps:\n{step_list}\n\n"
        f"Use get_plan to see full details, or update_plan_step to log progress."
    )


async def exec_get_plan(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Retrieve a plan by ID or title."""
    if registry._plan_store is None:
        return "Plan tracking not available."

    plan_id = inp.get("plan_id")
    title = inp.get("title", "").strip()

    if not plan_id and not title:
        return "Please provide either plan_id or a title to search for."

    try:
        if plan_id:
            plan = await registry._plan_store.get_plan(int(plan_id))
        else:
            plan = await registry._plan_store.get_plan_by_title(user_id, title)
    except Exception as e:
        return f"Could not fetch plan: {e}"

    if not plan:
        if plan_id:
            return f"No plan with ID {plan_id} found."
        return f"No plan matching '{title}' found."

    _STATUS_EMOJI = {
        "pending": "⬜",
        "in_progress": "🔄",
        "done": "✅",
        "skipped": "⏭️",
        "blocked": "🚫",
    }

    lines = [
        f"📋 **{plan['title']}** (ID {plan['id']})",
        f"Status: {plan['status']}",
    ]
    if plan.get("description"):
        lines.append(f"Description: {plan['description']}")
    lines.append(f"Created: {plan['created_at'][:10]} | Updated: {plan['updated_at'][:10]}")
    lines.append("")

    for step in plan.get("steps", []):
        emoji = _STATUS_EMOJI.get(step["status"], "❓")
        lines.append(f"{step['position']}. {emoji} [{step['status']}] {step['title']} (step ID {step['id']})")
        if step.get("notes"):
            lines.append(f"   Notes: {step['notes']}")
        for attempt in step.get("attempts", []):
            lines.append(
                f"   → {attempt['attempted_at'][:16]}: {attempt['outcome']}"
                + (f" — {attempt['notes']}" if attempt.get("notes") else "")
            )

    return "\n".join(lines)


async def exec_list_plans(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """List the user's plans with step progress and last activity."""
    if registry._plan_store is None:
        return "Plan tracking not available."

    status = inp.get("status", "active")

    try:
        plans = await registry._plan_store.list_plans(user_id, status)
    except Exception as e:
        return f"Could not list plans: {e}"

    if not plans:
        if status == "all":
            return "No plans found. Use create_plan to make one."
        return f"No {status} plans found. Use create_plan to make one, or list_plans with status='all' to see all."

    lines = [f"📋 Plans ({status}): {len(plans)}"]
    lines.append("")

    for plan in plans:
        counts = plan.get("step_counts", {})
        done = counts.get("done", 0)
        in_progress = counts.get("in_progress", 0)
        pending = counts.get("pending", 0)
        blocked = counts.get("blocked", 0)
        total = plan.get("total_steps", 0)

        progress_parts = []
        if done:
            progress_parts.append(f"{done} done")
        if in_progress:
            progress_parts.append(f"{in_progress} in progress")
        if pending:
            progress_parts.append(f"{pending} pending")
        if blocked:
            progress_parts.append(f"{blocked} blocked")
        progress = ", ".join(progress_parts) if progress_parts else "no steps"

        lines.append(f"**{plan['title']}** (ID {plan['id']})")
        lines.append(f"  [{total} steps — {progress}]")
        lines.append(f"  Last activity: {plan['updated_at'][:10]}")
        lines.append("")

    return "\n".join(lines)


async def exec_update_plan_step(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Update the status of a plan step and/or log a new attempt."""
    if registry._plan_store is None:
        return "Plan tracking not available."

    step_id = inp.get("step_id")
    status = inp.get("status")
    attempt_outcome = inp.get("attempt_outcome", "").strip()
    attempt_notes = inp.get("attempt_notes", "").strip() or None

    if not step_id:
        return "Please provide step_id. Use get_plan to find step IDs."

    results = []

    try:
        if status:
            updated = await registry._plan_store.update_step_status(int(step_id), status)
            if updated:
                results.append(f"Status → {status}")
            else:
                return f"No step with ID {step_id} found."

        if attempt_outcome:
            await registry._plan_store.add_attempt(int(step_id), attempt_outcome, attempt_notes)
            results.append(f"Attempt logged: {attempt_outcome}")
            if not status:
                await registry._plan_store.update_step_status(int(step_id), "in_progress")
                results.append("Status → in_progress (auto)")

    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Could not update step: {e}"

    if not results:
        return "No changes made. Provide status and/or attempt_outcome."

    return f"✅ Step {step_id} updated: " + "; ".join(results)


async def exec_update_plan_status(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Mark an entire plan as complete or abandoned."""
    if registry._plan_store is None:
        return "Plan tracking not available."

    plan_id = inp.get("plan_id")
    status = inp.get("status")

    if not plan_id:
        return "Please provide plan_id. Use list_plans to find plan IDs."
    if not status:
        return "Please provide status ('complete' or 'abandoned')."

    try:
        updated = await registry._plan_store.update_plan_status(int(plan_id), status)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Could not update plan: {e}"

    if not updated:
        return f"No plan with ID {plan_id} found."

    if status == "complete":
        return f"✅ Plan {plan_id} marked as complete. Well done! 🎉"
    return f"✅ Plan {plan_id} marked as {status}."
