#!/bin/bash
# Inject relay check-in reminder at session start (Remy project).
# Output: additional_context to reinforce CLAUDE.md
jq -n '{
  additional_context: "Session start: If you are Remy, run relay_get_messages(agent=\"remy\") and relay_get_tasks(agent=\"remy\", status=\"pending\") first. Claim any tasks before starting other work."
}'
exit 0
