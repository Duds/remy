#!/usr/bin/env python3
"""
Run progressive integration scenarios (Level 1 → 5) in order.

Used by the remy-integration-tester subagent to drive an iterative, live-loop
workflow: run scenarios → on failure, log and fix → re-run until green.

Levels:
  1 — Single-tool (main agent): stream yields events, one tool then reply.
  2 — Multi-tool (main agent): multiple tool calls in one turn.
  3 — Step-limit: max_iterations yields StepLimitReached (no auto Board hand-off, Bug 47).
  4 — Sub-agent runs after hand-off: hand-off then sub-agent uses tools.
  5 — Leaves / tools in depth: run_board (or other leaf) completes.

Usage (from repo root):
  PYTHONPATH=. python3 scripts/run_integration_scenarios.py
  PYTHONPATH=. python3 scripts/run_integration_scenarios.py --append-failures
  PYTHONPATH=. python3 scripts/run_integration_scenarios.py --level 3

Requirements:
  - pytest and project deps. No ANTHROPIC_API_KEY for pytest-based scenarios.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


@dataclass
class Scenario:
    level: int
    name: str
    pytest_selector: str  # e.g. "tests/test_tool_registry.py::test_foo"
    description: str


# Progressive scenarios: run in order. Each is a pytest selector (no live API).
PROGRESSIVE_SCENARIOS: list[Scenario] = [
    Scenario(
        1,
        "main_agent_stream_yields_events",
        "tests/test_tool_registry.py::test_stream_with_tools_yields_text_chunks",
        "Main agent stream yields text chunks (single-tool path).",
    ),
    Scenario(
        2,
        "main_agent_tool_then_reply",
        "tests/test_tool_registry.py::test_stream_with_tools_sequence_trace_multi_tool_then_reply",
        "Main agent uses tool then replies (event order and dispatch).",
    ),
    Scenario(
        3,
        "step_limit_on_max_iterations",
        "tests/test_tool_registry.py::test_stream_with_tools_hits_max_iterations_yields_truncation",
        "Max iterations yields step-limit message and StepLimitReached.",
    ),
    Scenario(
        4,
        "max_iterations_yields_step_limit",
        "tests/integration/test_subagent_tools.py::test_max_iterations_yields_step_limit_not_board_handoff",
        "Max iterations yields StepLimitReached (no Board hand-off, Bug 47).",
    ),
    Scenario(
        4,
        "subagent_tool_sequence_recorded",
        "tests/integration/test_subagent_tools.py::test_subagent_tool_sequence_recorded",
        "Sub-agent runs multiple tools in sequence; order recorded.",
    ),
    Scenario(
        5,
        "run_board_dispatch",
        "tests/test_tool_registry.py::test_dispatch_run_board_calls_orchestrator",
        "dispatch(run_board) calls BoardOrchestrator.",
    ),
    Scenario(
        5,
        "run_board_returns_report",
        "tests/test_agents.py::test_run_board_returns_formatted_report",
        "Board run returns formatted report (sub-agent / leaf path).",
    ),
]


def run_pytest(selector: str) -> tuple[bool, str]:
    """Run pytest for the given selector. Returns (passed, stderr+stdout)."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        selector,
        "-v",
        "--tb=short",
    ]
    result = subprocess.run(
        cmd,
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = (result.stderr or "") + "\n" + (result.stdout or "")
    return result.returncode == 0, output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run progressive integration scenarios (Level 1→5)."
    )
    parser.add_argument(
        "--level",
        type=int,
        choices=[1, 2, 3, 4, 5],
        help="Run only scenarios at this level (default: all).",
    )
    parser.add_argument(
        "--append-failures",
        action="store_true",
        help="Append failure details to docs/architecture/integration-test-errors-and-fixes.md.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List scenarios and exit.",
    )
    args = parser.parse_args()

    scenarios = PROGRESSIVE_SCENARIOS
    if args.level is not None:
        scenarios = [s for s in scenarios if s.level == args.level]

    if args.list:
        for s in scenarios:
            print(f"  L{s.level}  {s.name}: {s.pytest_selector}")
        return 0

    print("--- Progressive integration scenarios ---")
    print(f"Running {len(scenarios)} scenario(s) in order.\n")

    failed: list[tuple[Scenario, str]] = []
    for s in scenarios:
        print(f"[L{s.level}] {s.name} ... ", end="", flush=True)
        passed, output = run_pytest(s.pytest_selector)
        if passed:
            print("PASS")
        else:
            print("FAIL")
            failed.append((s, output))

    print()
    if not failed:
        print("--- All scenarios passed. ---")
        return 0

    print(f"--- {len(failed)} scenario(s) failed ---")
    for s, output in failed:
        print(f"\n  L{s.level} {s.name}")
        print(f"  Selector: {s.pytest_selector}")
        # Last 30 lines of output often enough to see assertion
        lines = output.strip().splitlines()
        tail = "\n".join(lines[-30:]) if len(lines) > 30 else output
        print(tail[:2000] + ("..." if len(tail) > 2000 else ""))

    if args.append_failures:
        doc = _REPO / "docs" / "architecture" / "integration-test-errors-and-fixes.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        with open(doc, "a", encoding="utf-8") as f:
            f.write("\n\n## run_integration_scenarios.py failures (appended)\n\n")
            for s, output in failed:
                f.write(f"- **L{s.level}** {s.name}\n")
                f.write(f"  Selector: `{s.pytest_selector}`\n")
                lines = output.strip().splitlines()
                tail = "\n".join(lines[-20:])
                f.write(f"  Output (tail):\n```\n{tail[:1500]}\n```\n\n")
        print(f"\nFailures appended to {doc}.")

    return 1


if __name__ == "__main__":
    sys.exit(main())
