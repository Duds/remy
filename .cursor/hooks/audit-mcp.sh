#!/bin/bash
# Audit MCP tool usage. Fires on afterMCPExecution.
LOG="${CURSOR_PROJECT_DIR:-.}/.cursor/audit.log"
mkdir -p "$(dirname "$LOG")"
tool=$(jq -r '.tool_name // empty' 2>/dev/null)
dur=$(jq -r '.duration // 0' 2>/dev/null)
ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
# Only log relay tools (high signal for Remy)
case "$tool" in
  relay_*)
    echo "[$ts] mcp | $tool | ${dur}ms" >> "$LOG"
    ;;
esac
exit 0
