#!/usr/bin/env bash
# remy startup script — run by launchd LaunchAgent at login
# Ensures Docker Desktop is running then starts remy + relay + ollama via docker compose.
# Uses detached mode (-d) so the script exits and containers run as daemons.
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

# Start remy + relay + ollama in detached mode (daemon)
# Containers persist under Docker; script exits so launchd job completes
docker compose --project-directory "$PROJECT_DIR" up -d remy relay ollama
