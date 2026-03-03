---
name: SHIP-IT
description: Full deployment pipeline for Remy — completes docs, restarts Docker + bot, runs tests and diagnostics, commits everything and pushes to remote. Use when the user says /SHIP-IT or wants to ship a release.
disable-model-invocation: true
---

# SHIP-IT — Remy Deployment Pipeline

## Current State
- Branch: !`git branch --show-current`
- Uncommitted changes: !`git status --short`
- Unpushed commits: !`git log @{u}..HEAD --oneline 2>/dev/null || echo "(no upstream set)"`
- Recent commits: !`git log --oneline -5`

---

Execute each phase in order. After every phase, record ✅ pass or ❌ fail. Present the final summary table before exiting.

## Phase 1 — Documentation

1. Read `BUGS.md` and `TODO.md`. For any item marked done or resolved in code but not yet struck through, update the file to mark it complete.
2. Read `CLAUDE.md`. Check that the key files, session key format, and open bugs sections match the current codebase. Update any stale entries (e.g. bug status, file paths, architecture notes).
3. If a `docs/` directory exists, scan for any `.md` files containing `TODO` or `FIXME` and resolve or note them.
4. Check `README.md` (if present) for obviously outdated instructions (wrong Python version, missing env vars, stale commands).

Do not over-engineer — only update what is clearly wrong or resolved. Keep edits minimal and precise.

## Phase 2 — Docker Restart

Run these commands from the project root `/Users/dalerogers/Projects/ai-agents/remy`:

```bash
cd /Users/dalerogers/Projects/ai-agents/remy

# Kill any zombie remy/python processes from previous runs
pkill -f "python.*remy" 2>/dev/null || true
pkill -f "remy.main" 2>/dev/null || true

# Tear down existing containers
docker compose down --remove-orphans

# Prune stopped containers, dangling images, unused networks, and build cache
docker system prune -f
docker builder prune -f

# Rebuild and start
docker compose up --build -d
```

Wait for the health check to pass (up to 60 seconds):

```bash
sleep 20
curl -sf http://localhost:8080/health | python3 -m json.tool
```

If health check fails after 60 seconds, capture `docker compose logs remy --tail 50` and report the error. Do not proceed to Phase 4 (restart is considered failed).

## Phase 3 — Remy Process Check

Confirm the bot container is running and healthy:

```bash
docker compose ps
docker compose logs remy --tail 20
```

Look for "Remy is online" or the Telegram polling startup message in the logs. If the bot process has crashed or is restarting, capture the error and mark Phase 3 as ❌.

## Phase 4 — Tests & Diagnostics

Run the full test suite and linters:

```bash
cd /Users/dalerogers/Projects/ai-agents/remy
python3 -m pytest tests/ -v --tb=short 2>&1
```

```bash
python3 -m ruff check remy/ tests/ 2>&1
python3 -m mypy remy/ --ignore-missing-imports 2>&1
```

Record:
- Total tests passed / failed / errored
- Any lint errors (file:line)
- Any mypy type errors

If tests fail, do NOT abort — record failures and continue to Phase 5. The commit message will note failing tests.

## Phase 5 — Commit & Push

Stage all modified tracked files plus any new files in `remy/`, `tests/`, `docs/`, `BUGS.md`, `TODO.md`, `CLAUDE.md`, `README.md`:

```bash
cd /Users/dalerogers/Projects/ai-agents/remy
git add remy/ tests/ docs/ BUGS.md TODO.md CLAUDE.md README.md 2>/dev/null; git add -u
git status --short
```

Draft a commit message that:
- Summarises what actually changed (use `git diff --cached --stat`)
- Notes if tests are passing or failing
- Is concise (≤72 chars subject line, optional body)
- Ends with `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

Commit:
```bash
git commit -m "<message>"
```

Then push:
```bash
git push
```

If push is rejected (non-fast-forward), report the conflict and do NOT force-push. Ask the user how to proceed.

---

## Final Summary

Present this table after all phases complete:

| Phase | Task | Result | Notes |
|-------|------|--------|-------|
| 1 | Documentation | ✅/❌ | Files updated / issues found |
| 2 | Docker restart | ✅/❌ | Health check pass/fail |
| 3 | Remy bot online | ✅/❌ | Startup log snippet |
| 4 | Tests & lint | ✅/❌ | X passed, Y failed, Z lint errors |
| 5 | Commit & push | ✅/❌ | Commit SHA + push result |

If any phase is ❌, list the specific errors and suggest next steps.