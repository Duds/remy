#!/bin/bash
# Block reading sensitive files (Remy project). Fires on beforeReadFile.
# Exit 2 = block. Exit 0 = allow.

path=$(jq -r '.file_path // .path // .tool_input.file_path // .tool_input.path // empty' 2>/dev/null)
[[ -z "$path" ]] && exit 0

# Normalise path (strip leading ./)
path="${path#./}"

# Protected patterns: secrets, DB files, credentials
case "$path" in
  .env*|*.env|data/*.db|data/*.db-*|credentials*.json|*client_secrets*|*.pem|*.key)
    jq -n --arg p "$path" '{
      continue: true,
      permission: "deny",
      user_message: "Sensitive file access blocked.",
      agent_message: ("Blocked read of " + $p + ". Secrets, DB files, and credentials are protected. Use environment variables or ask the user for specific values.")
    }'
    exit 2
    ;;
esac

exit 0
