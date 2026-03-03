#!/bin/bash
# Auto-format Python files after edit. Fires on afterFileEdit.
# Non-blocking; exit 0 always.

path=$(jq -r '.file_path // .path // .tool_input.file_path // .tool_input.path // empty' 2>/dev/null)
[[ -z "$path" ]] || [[ ! -f "$path" ]] && exit 0

case "$path" in
  *.py)
    if command -v ruff &>/dev/null; then
      ruff format "$path" 2>/dev/null
    elif command -v black &>/dev/null; then
      black -q "$path" 2>/dev/null
    fi
    ;;
esac

exit 0
