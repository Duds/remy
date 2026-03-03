#!/bin/bash
# Audit subagent completion. Fires on subagentStop.
LOG="${CURSOR_PROJECT_DIR:-.}/.cursor/audit.log"
mkdir -p "$(dirname "$LOG")"
type=$(jq -r '.subagent_type // empty' 2>/dev/null)
status=$(jq -r '.status // empty' 2>/dev/null)
dur=$(jq -r '.duration // 0' 2>/dev/null)
ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
echo "[$ts] subagent | type=$type | status=$status | ${dur}ms" >> "$LOG"
exit 0
