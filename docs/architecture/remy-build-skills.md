# Remy Build Prompt — Skills System

## Context

You are implementing the skills system for Remy, a personal AI assistant built on a Telegram bot framework (Python, asyncio). The skills system is part of the P2 implementation phase, developed alongside the sub-agent system.

Remy already has:
- `config/SOUL.md` — personality and behavioural instructions, loaded into every conversation
- `config/HEARTBEAT.md` + `HEARTBEAT.local.md` — heartbeat evaluation rules
- `config/TASK.md` + `TASK.local.md` — orchestrator coordination rules
- `remy/agents/runner.py` — SubagentRunner (assume complete)
- `remy/agents/orchestrator.py` — Orchestrator (assume complete)
- `remy/agents/workers/research.py` — ResearchAgent (build together with this system)

The skills system extends the existing config pattern to task-type-specific behavioural instructions.

---

## Design Principles

**Skills are Markdown, not code.**

Behavioural logic in Python is expensive to change, requires deployment, and is invisible to a non-developer. Behavioural logic in a Markdown file is cheap to iterate, reviewable in git, personalised via `*.local.md`, and hot-reloadable without a restart.

All skill behaviour starts in config. It only moves to code when config is provably insufficient.

---

## What to Build

### 1. remy/skills/loader.py

Single utility module. All skill injection points use this — no inline file reads anywhere else in the codebase.

```python
from pathlib import Path

SKILLS_DIR = Path("config/skills")

def load_skill(name: str) -> str:
    """
    Load base + local skill file for a given skill name.
    Returns merged string, or empty string if neither file exists.
    Local overrides are appended after base content.
    """
    base = SKILLS_DIR / f"{name}.md"
    local = SKILLS_DIR / f"{name}.local.md"
    parts = [p.read_text(encoding="utf-8") for p in [base, local] if p.exists()]
    return "\n\n".join(parts).strip()


def load_skills(names: list[str]) -> str:
    """
    Load and concatenate multiple skills.
    Skills are separated by a horizontal rule for clarity in the context window.
    Missing skills are silently skipped.
    """
    loaded = [load_skill(n) for n in names]
    return "\n\n---\n\n".join(s for s in loaded if s)
```

Requirements:
- Return empty string (not raise) if no skill files exist for a name
- UTF-8 encoding throughout
- No caching — read from disk at call time (hot-reload by design)
- No logging unless a file is expected but missing (log a warning, do not raise)

---

### 2. Skill injection points

Update the following files to inject skills at the right moment. Do not change the existing system prompt or SOUL.md loading logic — skills are additive, appended after the base context.

#### remy/agents/runner.py

At worker spawn, load the skill for the worker type and pass it into the worker's context:

```python
from remy.skills.loader import load_skill

# When spawning a worker:
skill_context = load_skill(worker_type)  # e.g. "research", "goal-planning", "code-review"
# Inject skill_context into the worker's system prompt alongside task_context
```

#### remy/agents/orchestrator.py

At task-start, load the relevant skill alongside TASK.md:

```python
from remy.skills.loader import load_skill

# When building the orchestrator system prompt:
task_md = Path("config/TASK.md").read_text()
skill = load_skill(task_type)  # task_type derived from the task manifest
system_prompt = f"{task_md}\n\n---\n\n{skill}".strip()
```

#### remy/scheduler/heartbeat.py

When a threshold fires, load the threshold-specific skill to shape output format:

```python
from remy.skills.loader import load_skill

# Threshold → skill mapping:
THRESHOLD_SKILLS = {
    "daily_orientation": "daily-briefing",
    "end_of_day": "daily-briefing",
    "meeting_prep": "meeting-prep",
    "email_triage": "email-triage",
}

# When building the heartbeat inference call:
skill_name = THRESHOLD_SKILLS.get(threshold_type)
skill = load_skill(skill_name) if skill_name else ""
```

#### remy/bot/handlers/chat.py

When intent is detected for a known task type, inject the relevant skill into that inference call only. Skills do not persist across turns.

```python
from remy.skills.loader import load_skills

# Intent → skill mapping (extend as needed):
INTENT_SKILLS = {
    "email_reply": ["email-triage"],
    "meeting_prep": ["meeting-prep"],
    "code_review": ["code-review"],
    "goal_plan": ["goal-planning"],
    "research": ["research"],
}

# At inference call build time:
intent = detect_intent(message)  # existing intent detection
skills = load_skills(INTENT_SKILLS.get(intent, []))
# Append skills to system prompt for this call only
```

---

### 3. Skill files

Create the following files in `config/skills/`. Each file is a Markdown document with instructions written directly to the model. Write as instructions, not descriptions.

#### config/skills/research.md

Instructions for the ResearchAgent worker. Must include:
- How to scope a research task (identify the core question before searching)
- Source hierarchy: primary sources before secondary, official documentation before commentary
- How to handle conflicting information
- Output format: structured findings, not prose summaries
- When to spawn sub-topics vs stay focused on the original scope
- JSON output schema:
  ```json
  {
    "summary": "one paragraph",
    "findings": ["finding 1", "finding 2"],
    "gaps": ["what could not be found or confirmed"],
    "sources": ["url or citation"],
    "relevant_goals": ["goal ids if applicable"]
  }
  ```

#### config/skills/daily-briefing.md

Instructions for the heartbeat daily orientation output. Must include:
- Structure: priorities first, then calendar, then open tasks, then flagged items
- Keep total output under 300 words
- Flag only items that require a decision or action today — do not surface informational items
- Tone: direct, no pleasantries
- Do not repeat items from the previous briefing unless status has changed

#### config/skills/email-triage.md

Instructions for email triage and draft reply tasks. Must include:
- Priority classification: urgent/action-required/informational/noise
- What makes an email urgent (explicit deadline, named sender in priority list, blocking someone else)
- How to structure a draft reply: purpose in the first sentence, action or decision requested clearly stated
- When to suggest archiving vs responding vs forwarding
- Length guidance: match reply length to the original email's tone and complexity

#### config/skills/goal-planning.md

Instructions for the GoalWorker when decomposing or advancing a goal. Must include:
- How to break a goal into the smallest actionable steps
- Step format: verb + object + measurable outcome ("Write first draft of X, producing a complete document with all sections filled")
- How to identify blockers vs next actions
- When a step is genuinely blocked vs when it just needs to be started
- Output format: updated step list with statuses and a single identified next action

#### config/skills/meeting-prep.md

Instructions for the meeting preparation threshold. Must include:
- What to surface: attendees, agenda items, linked documents, open decisions
- How to flag if a meeting has no agenda or no linked documents
- Time guidance: surface 30 minutes before the meeting, not earlier
- Output format: brief bullets, no prose
- If the meeting is a recurring 1:1, note the last discussed topic if available in memory

#### config/skills/code-review.md

Instructions for the CodeAgent when reviewing diffs. Must include:
- Review order: correctness first, then tests, then style
- What to flag: logic errors, missing error handling, security concerns, unhandled edge cases
- What not to flag: style preferences that have no correctness implication
- Output format: structured list grouped by severity (blocking / non-blocking / suggestion)
- Keep total review output under 500 words — surface the most important issues only

---

### 4. .gitignore update

Add the following line to `.gitignore`:

```
config/skills/*.local.md
```

This is already covered by the existing `config/*.local.md` wildcard if present. Confirm it is in place and add the skills-specific line as a belt-and-braces measure.

---

### 5. config/skills/README.md

Create a short README in the skills directory documenting:
- What a skill file is
- How to author a new skill
- How `*.local.md` overrides work
- The 500-word limit
- Which injection point to use for a new skill type

---

## Implementation Sequence

Do not proceed to step N+1 until step N has passing tests.

1. `remy/skills/loader.py` — implement and unit test (missing file returns empty string, local override appends correctly, load_skills concatenates with separator)
2. `config/skills/research.md` — write skill file
3. Wire skill injection into `remy/agents/workers/research.py` — validate that ResearchAgent output conforms to the skill's JSON schema
4. `config/skills/daily-briefing.md` — write skill file, wire into `heartbeat.py`
5. `config/skills/email-triage.md` — write skill file, wire into `chat.py` intent detection
6. `config/skills/goal-planning.md` — write skill file, wire into `remy/agents/workers/goal.py`
7. `config/skills/meeting-prep.md` — write skill file, wire into heartbeat meeting threshold
8. `config/skills/code-review.md` — write skill file, wire into `remy/agents/workers/code.py`
9. `config/skills/README.md` — document the pattern

---

## Constraints

- Skills are injected per-call only — never merged into SOUL.md or the base system prompt
- Skills do not persist across conversation turns
- The model does not select its own skills — injection points are explicit in code
- No skill registry, no skill discovery, no versioning layer beyond git
- Flat directory structure — one level of local override only, no hierarchies
- Each skill file stays under 500 words

---

## File Paths

```
remy/skills/__init__.py
remy/skills/loader.py
config/skills/research.md
config/skills/daily-briefing.md
config/skills/email-triage.md
config/skills/goal-planning.md
config/skills/meeting-prep.md
config/skills/code-review.md
config/skills/README.md
```

Modified files:
```
remy/agents/runner.py          — add skill injection at worker spawn
remy/agents/orchestrator.py   — add skill injection at task-start
remy/scheduler/heartbeat.py   — add skill injection on threshold fire
remy/bot/handlers/chat.py     — add skill injection on intent detection
.gitignore                     — confirm *.local.md wildcard covers skills/
```
