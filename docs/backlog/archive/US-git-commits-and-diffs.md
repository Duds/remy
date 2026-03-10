# User Story: Git Commits and Diffs Tool

**Status:** ✅ Done

## Summary

As a user, I want Remy to inspect git commits and diffs in her codebase so that I can ask "what changed in the last few commits?", "show me the diff for that fix", or "what's different between main and this branch?" without leaving the conversation.

---

## Background

Remy has filesystem tools (`read_file`, `search_files`, `list_dir`) but no way to query git history or diffs. Users and cowork may ask about recent changes, blame, or branch comparisons. Today Remy cannot answer those questions without the user running `git log` or `git diff` themselves.

A **read-only** git tool keeps the agent from modifying the repo (no commit, push, checkout, reset). The tool should operate on the workspace repository; the working directory can be configurable (e.g. `Settings` or tool param) for monorepos or when Remy runs from a different cwd.

Related: `remy/ai/tools/files.py`, `remy/ai/tools/schemas.py`, `remy/ai/tools/registry.py`, `remy/config.py`.

---

## Acceptance Criteria

1. **List commits (log).** A tool (e.g. `git_log`) accepts:
   - `ref` (optional): branch/tag/commit to start from (default: `HEAD`).
   - `limit` (optional): max number of commits (default: 10, cap e.g. 50).
   - `path` (optional): limit to commits that touched this path.
   - Returns: list of commits with `hash` (short), `subject`, `author`, `date` (ISO or relative).
2. **Show one commit.** A tool (e.g. `git_show_commit`) accepts a commit ref (hash or branch). Returns full message body, author, date, and optionally the list of changed files (names only, no diff).
3. **Show diff.** A tool (e.g. `git_diff`) accepts:
   - Either: single `commit` (show that commit’s diff vs its parent).
   - Or: `base` and `head` (e.g. `main` and `feature/x`) to compare two refs.
   - Optional `path` to limit diff to one file/directory.
   - Output is plain-text unified diff; length capped (e.g. 32 KB) with truncation note if exceeded.
4. **Working tree status (optional).** A tool (e.g. `git_status`) returns current branch, short status (clean / ahead/behind, list of modified/untracked files). No staging details required for MVP.
5. **Read-only.** No subcommands or code paths that run `git commit`, `git push`, `git checkout -f`, `git reset --hard`, or any other mutating operation.
6. **Workspace.** Tool runs in the configured workspace root (e.g. `Settings.workspace_root` or repo root derived from cwd). Clear error if not in a git repo.
7. **Tool visibility.** New tool(s) appear in the tool registry with clear descriptions so the model can choose when to use them.

---

## Implementation

**Files:** `remy/config.py` (if adding `workspace_root`), `remy/ai/tools/git.py` (new), `remy/ai/tools/schemas.py`, `remy/ai/tools/registry.py`.

### 1. Git helper module

- New `remy/ai/tools/git.py` with sync functions (e.g. `run_git(...)`) that run `git` in the workspace directory via `subprocess`, with no shell injection (args as list, no user input in shell).
- Implement: `git_log(ref, limit, path)`, `git_show_commit(ref)`, `git_diff(commit=None, base=None, head=None, path=None)`, optionally `git_status()`.
- Enforce output caps and return truncated content with a note when exceeded.

### 2. Tool schema and registry

- In `schemas.py`, add parameters and descriptions for:
  - `git_log`: `ref`, `limit`, `path` (all optional).
  - `git_show_commit`: `ref` (required).
  - `git_diff`: either `commit` or `base`+`head`, plus optional `path`.
- Register in `registry.py` and wire to the git helper. Restrict to read-only routes (e.g. quick-assistant) if needed; no need for board-analyst unless desired.

### 3. Configuration

- If the codebase has no single “workspace root”, add `workspace_root: Path | None` to Settings (default None = derive from cwd or detect repo root). Git helpers use this as the working directory for all `git` invocations.

### Notes

- Use `git log -n N`, `git show --format=...`, `git diff base..head` (or `commit^..commit` for single-commit diff). Avoid `--no-pager` and ensure output is captured, not TTY.
- Date format: ISO 8601 or relative (e.g. "2 days ago") is fine; keep consistent.
- Consider one combined tool `git` with a `subcommand` parameter (log / show / diff / status) if that fits the existing registry pattern better than four separate tools.

---

## Test Cases

| Scenario | Expected |
|----------|----------|
| `git_log(limit=5)` in repo | Returns 5 most recent commits with hash, subject, author, date |
| `git_log(ref="main", path="remy/ai")` | Only commits touching `remy/ai` on main |
| `git_show_commit("abc1234")` | Full message, author, date, list of changed files |
| `git_diff(commit="abc1234")` | Unified diff for that commit |
| `git_diff(base="main", head="HEAD")` | Diff between main and current branch |
| `git_diff(base="main", head="HEAD", path="remy/ai/tools/git.py")` | Diff limited to that file |
| Diff output > 32 KB | Truncated with note |
| Call from non-git directory (or no workspace_root) | Clear error, no crash |
| Any attempt to pass through commit/push/reset | Not exposed; only read-only commands implemented |

---

## Out of Scope

- Writing to git (commit, push, checkout, reset, merge, rebase).
- Staging or unstaging files.
- Blame / annotate (can be a follow-up).
- Remote operations (fetch, ls-remote) — read-only local history only for this story.
