#!/usr/bin/env bash
# remy startup script — sourced by launchd LaunchAgent
# Ensures Docker Desktop is running then starts remy via docker compose.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Launch Docker Desktop if it's not already running
if ! pgrep -x "Docker" >/dev/null 2>&1; then
    open -a Docker
fi

# Wait for Docker daemon to be ready (up to 120s)
WAIT=0
until docker info >/dev/null 2>&1; do
    sleep 3
    WAIT=$((WAIT + 3))
    if [ "$WAIT" -ge 120 ]; then
        echo "$(date): Docker daemon did not start in time — aborting" >&2
        exit 1
    fi
done

# Start (or resume) the remy stack
exec docker compose --project-directory "$PROJECT_DIR" up
