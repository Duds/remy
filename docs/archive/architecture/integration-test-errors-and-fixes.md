# Integration test errors and fixes

Log of failures encountered while building or running Remy integration tests (trace script, `tests/integration/`, tool registry), with root cause and fix.

## Progressive scenario runner (iterative workflow)

The **remy-integration-tester** subagent is required to work in an **iterative, live loop** with **progressively more complex** scenarios (agent → sub-agent → leaf), not a one-shot run.

- **Runner:** `PYTHONPATH=. python3 scripts/run_integration_scenarios.py`
- **Levels:** 1 single-tool (main agent) → 2 multi-tool → 3 hand-off → 4 sub-agent runs after hand-off → 5 leaves/tools (e.g. run_board). Each level runs one or more pytest-based scenarios in order.
- **Loop:** Run runner → on any failure, log (Error/Cause/Fix) below, fix code or test, re-run runner until all pass → then advance. Use `--append-failures` to append failure output to this doc.
- **List scenarios:** `scripts/run_integration_scenarios.py --list`
- **Single level:** `scripts/run_integration_scenarios.py --level 3`

See `.cursor/agents/remy-integration-tester.md` for the full workflow and scope.

Format for each entry:

- **Date**
- **Error:** What failed (test name, command, scenario) and observed message/behaviour
- **Cause:** Brief root cause
- **Fix:** File(s) and change(s) made

---

## 2026-03-09 — Tool dispatch coverage added

- **Change:** Added `tests/integration/test_tool_dispatch_coverage.py` to cover every tool in `TOOL_SCHEMAS` (83 tools) with a parametrized integration test that calls `ToolRegistry.dispatch()` with minimal input and asserts the result is a string and not "Unknown tool".
- **Result:** All 86 tests (83 parametrized + 3 extra for get_current_time, suggest_actions, relay) pass. No failures. Full integration suite and `tests/test_tool_registry.py` (153 tests total) pass. `scripts/trace_agent_sequence.py "What time is it?"` runs successfully with live API.
- **Fix:** N/A (no failures).

*(Entries added by the remy-integration-tester subagent.)*

---

## 2026-03-09 — Full workflow run (no failures)

- **Run:** Full remy-integration-tester workflow: (1) `scripts/run_integration_scenarios.py`, (2) pytest `tests/integration/` + `tests/test_tool_registry.py`, (3) `scripts/trace_agent_sequence.py "What time is it? Then list my goals."`
- **Result:** All passed. Progressive scenarios: 7/7 (L1–L5). Pytest: 153 passed. Trace script: 33 events, 2 tool turns (get_current_time, get_goals), streamed reply; get_goals returned "Goal store not available" (expected without DB).
- **Fix:** N/A (no failures).

---

## 2026-03-09 — Progressive scenario runner and iterative workflow

- **Change:** Updated remy-integration-tester agent spec to require an **iterative, live-loop** workflow: run progressively more complex scenarios (Level 1→5), search for errors, log and fix, re-run until green. Added `scripts/run_integration_scenarios.py` that runs 7 scenarios in order (main agent stream → tool then reply → hand-off → sub-agent uses tools → run_board). All scenarios pass (pytest-based; no live API).
- **Result:** Agent spec now explicitly requires: do not do one-shot parametrized coverage only; loop run → fix → re-run and advance by level. Documentation in this file and in `.cursor/agents/remy-integration-tester.md` updated.
- **Fix:** N/A (no test failures).
