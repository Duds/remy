# Skills — Behavioural Instructions for Task Types

Skills are Markdown files that inject task-type-specific instructions into the model context at the moment a task starts. They extend the base behaviour defined in `SOUL.md`, `HEARTBEAT.md`, and `TASK.md`.

**Skills are Markdown, not code.** Behavioural logic that lives here can be changed by editing a text file — no deployment needed. Only move logic to Python when Markdown is provably insufficient.

---

## How Skills Work

At task-start, `remy/skills/loader.py` reads the relevant skill file and injects it into the system prompt alongside `TASK.md` (for workers) or `HEARTBEAT.md` (for heartbeat thresholds).

Skills are injected **per-call only** — they do not persist across conversation turns and are never merged into `SOUL.md`.

The model does not select its own skills. Injection points are explicit in code.

---

## File Structure

```
config/skills/
  research.md          # ResearchAgent worker instructions
  daily-briefing.md    # Heartbeat daily orientation output format
  email-triage.md      # Email triage and draft reply instructions
  goal-planning.md     # GoalWorker step decomposition instructions
  meeting-prep.md      # Heartbeat meeting prep threshold output
  code-review.md       # CodeAgent diff review instructions
  *.local.md           # gitignored — personal overrides per skill
  README.md            # this file
```

---

## Authoring a New Skill

1. Create `config/skills/{name}.md`
2. Write instructions directly to the model — use imperative voice, not descriptions
3. Keep it under **500 words**
4. Add the injection point in code (see below)
5. Optionally create `config/skills/{name}.local.md` for personal overrides (gitignored)

### Naming conventions

Use lowercase kebab-case: `email-triage`, `goal-planning`, `meeting-prep`.
Worker-type skills match the worker_type value: `research`, `goal`, `code`.

---

## Local Overrides

`{name}.local.md` is appended after the base file content. Use it for personal preferences that should not be committed:

```
config/skills/research.local.md   ← add personal source preferences
config/skills/daily-briefing.local.md  ← add personal briefing format
```

All `*.local.md` files are gitignored.

---

## Injection Points

| Skill | Injection Point | File |
|---|---|---|
| Worker skills (`research`, `goal`, `code`) | At worker spawn | `remy/agents/runner.py` |
| Orchestrator skill | At synthesis call | `remy/agents/task_orchestrator.py` |
| Heartbeat thresholds | On threshold fire | `remy/scheduler/heartbeat.py` |
| Conversation intent | On intent detection | `remy/bot/handlers/chat.py` |

---

## Loader API

```python
from remy.skills.loader import load_skill, load_skills

skill = load_skill("research")          # single skill
merged = load_skills(["email-triage"])  # multiple skills, separated by ---
```

Both functions return empty string (never raise) if no file exists.
