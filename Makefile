.PHONY: run test test-cov lint build docker-run docker-stop setup db db-init \
        deploy deploy-update deploy-logs deploy-delete health \
        remy-up relay-up relay-run relay-stop relay-check relay-setup-check relay-verify \
        install-launchd uninstall-launchd \
        tunnel-up tunnel-stop tunnel-logs telemetry logs ship-it-remote \
        qmd-search qmd-query

# ── Local development ─────────────────────────────────────────────────────────
run:
	python3 -m remy.main

setup:
	rm -rf .venv
	python3 -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

test:
	python3 -m pytest tests/ -v

test-cov:
	python3 -m pytest tests/ -v --cov=remy --cov-report=term-missing

lint:
	python3 -m ruff check remy/ tests/
	python3 -m mypy remy/ --ignore-missing-imports

# ── qmd — quick memory search (paperclip-ideas §10) ─────────────────────────
## Search remy's memory (facts, knowledge, goals) with BM25 keyword search.
## Usage: make qmd-search Q="health habits"
qmd-search:
	python3 -m remy.cli.qmd search "$(Q)"

## Alias for qmd-search (semantic / keyword search).
## Usage: make qmd-query Q="health habits"
qmd-query:
	python3 -m remy.cli.qmd query "$(Q)"

# ── Datasette (local DB browser) ──────────────────────────────────────────────
db-init:
	mkdir -p data
	python3 scripts/init_db.py

db: db-init
	python3 -m datasette serve data/remy.db --metadata config/datasette.yml --open

# ── Remy stack & Relay MCP (Claude Desktop / Claude Code, US-relay-shared-backend) ─
# Start full stack (remy bot + relay + ollama) via Docker. One relay process, one DB (data/relay.db).
remy-up:
	docker compose up -d remy relay ollama

# Alias: relay-up kept for backward compatibility
relay-up: remy-up

# Run relay server locally (no Docker) — single process, single DB at data/relay.db
# Prefer venv Python so mcp is available (pip install -r requirements.txt first)
PYTHON ?= $(if $(wildcard .venv/bin/python3),.venv/bin/python3,python3)
relay-run:
	@mkdir -p data
	$(PYTHON) relay_mcp/server.py --db data/relay.db

# Check if relay is reachable on port 8765
# Stop any process listening on relay port (e.g. previous relay-run or relay-up)
relay-stop:
	@lsof -ti:8765 | xargs kill -9 2>/dev/null || true
	@echo "relay port 8765 cleared"

relay-check:
	@python3 -c "import socket; s = socket.create_connection(('127.0.0.1', 8765), timeout=3); s.close(); print('relay OK')" || \
		echo "relay not reachable — run 'make remy-up' or 'make relay-run'"

# Verify Claude Desktop relay setup (relay + uv)
relay-setup-check: relay-check
	@command -v uvx >/dev/null 2>&1 || (echo "uv not found — install with: brew install uv"; exit 1)
	@echo "relay setup OK — relay running, uv available"

# Run relay tests (shared-DB E2E: remy↔cowork delivery on one DB). Use 'make relay-verify' or 'make relay'.
relay-verify:
	$(PYTHON) -m pytest tests/test_tools/test_relay.py -v
relay: relay-verify

# ── LaunchAgent (start at login) ───────────────────────────────────────────────
# Install LaunchAgent so remy + relay + ollama start when you log in
LAUNCH_AGENTS := $(HOME)/Library/LaunchAgents
REMY_PLIST := com.dalerogers.remy.plist

install-launchd:
	@mkdir -p data
	@sed "s|__PROJECT_DIR__|$(CURDIR)|g" config/com.dalerogers.remy.plist.template > $(LAUNCH_AGENTS)/$(REMY_PLIST)
	@launchctl load $(LAUNCH_AGENTS)/$(REMY_PLIST)
	@echo "LaunchAgent installed — remy stack will start at next login"
	@echo "To start now: make remy-up"

uninstall-launchd:
	@launchctl unload $(LAUNCH_AGENTS)/$(REMY_PLIST) 2>/dev/null || true
	@rm -f $(LAUNCH_AGENTS)/$(REMY_PLIST)
	@echo "LaunchAgent uninstalled"

# ── Docker (local) ────────────────────────────────────────────────────────────
build:
	docker build -t remy:latest .

docker-run:
	docker compose up --build

docker-stop:
	docker compose down

# Quick health check against local or remote container
# Usage: make health HOST=localhost PORT=8080
HOST ?= localhost
PORT ?= 8080
health:
	@curl -sf http://$(HOST):$(PORT)/health | python3 -m json.tool || \
		echo "Health check failed — is remy running?"

# ── Cloudflare Tunnel ─────────────────────────────────────────────────────────
# Requires CLOUDFLARE_TUNNEL_TOKEN in .env (see .env.example for setup steps)

# Start remy + relay + ollama + cloudflared tunnel
tunnel-up:
	docker compose --profile tunnel up -d

# Stop everything including tunnel
tunnel-stop:
	docker compose --profile tunnel down

# Follow cloudflared logs
tunnel-logs:
	docker compose logs -f cloudflared

# ── Remote observability ───────────────────────────────────────────────────────
# Usage: make telemetry HOST=remy.yourdomain.com TOKEN=<HEALTH_API_TOKEN>
#        make logs HOST=remy.yourdomain.com TOKEN=<HEALTH_API_TOKEN> LINES=200

TOKEN ?=
LINES ?= 100

telemetry:
	@curl -sf \
		$(if $(TOKEN),-H "Authorization: Bearer $(TOKEN)") \
		https://$(HOST)/telemetry | python3 -m json.tool

logs:
	@curl -sf \
		$(if $(TOKEN),-H "Authorization: Bearer $(TOKEN)") \
		"https://$(HOST)/logs?lines=$(LINES)" || \
		echo "Logs fetch failed — is the tunnel running?"

# Remote SHIP-IT: trigger fetch, diff, tests on the host over the tunnel.
# Requires HEALTH_API_TOKEN. Set DRY_RUN=1 to skip running tests.
DRY_RUN ?=
ship-it-remote:
	@curl -sf -X POST \
		-H "Authorization: Bearer $(TOKEN)" \
		-H "Content-Type: application/json" \
		$(if $(DRY_RUN),-d '{"dry_run":true}',-d '{}') \
		"https://$(HOST)/commands/ship-it" | python3 -m json.tool || \
		echo "SHIP-IT request failed — is the tunnel running and TOKEN set?"

# ── Azure deployment ──────────────────────────────────────────────────────────
# Required env vars (set in shell or .env.azure):
#   ACR_NAME          — Azure Container Registry name (e.g. myacr)
#   RESOURCE_GROUP    — Azure resource group
#   STORAGE_ACCOUNT   — Azure Storage Account name (for SQLite persistence)
#   STORAGE_KEY       — Azure Storage Account key
#   STORAGE_SHARE     — Azure File Share name (e.g. remy-data)
#   TELEGRAM_BOT_TOKEN
#   ANTHROPIC_API_KEY

# Push image to ACR then create/replace the container instance
deploy: build
	@echo "── Pushing image to ACR: $(ACR_NAME) ──"
	az acr login --name $(ACR_NAME)
	docker tag remy:latest $(ACR_NAME).azurecr.io/remy:latest
	docker push $(ACR_NAME).azurecr.io/remy:latest

	@echo "── Creating Azure Container Instance ──"
	az container create \
		--resource-group $(RESOURCE_GROUP) \
		--name remy \
		--image $(ACR_NAME).azurecr.io/remy:latest \
		--registry-login-server $(ACR_NAME).azurecr.io \
		--registry-username $(ACR_NAME) \
		--registry-password $$(az acr credential show --name $(ACR_NAME) --query passwords[0].value -o tsv) \
		--azure-file-volume-account-name $(STORAGE_ACCOUNT) \
		--azure-file-volume-account-key $(STORAGE_KEY) \
		--azure-file-volume-share-name $(STORAGE_SHARE) \
		--azure-file-volume-mount-path /data \
		--cpu 0.5 \
		--memory 1.5 \
		--restart-policy Always \
		--ports 8080 \
		--protocol TCP \
		--environment-variables \
			AZURE_ENVIRONMENT=true \
			HEALTH_PORT=8080 \
		--secure-environment-variables \
			TELEGRAM_BOT_TOKEN=$(TELEGRAM_BOT_TOKEN) \
			ANTHROPIC_API_KEY=$(ANTHROPIC_API_KEY)
	@echo "── Deployment complete ──"
	@$(MAKE) deploy-status

# Update the image on an existing container (faster than full re-create)
deploy-update: build
	@echo "── Pushing updated image to ACR ──"
	az acr login --name $(ACR_NAME)
	docker tag remy:latest $(ACR_NAME).azurecr.io/remy:latest
	docker push $(ACR_NAME).azurecr.io/remy:latest
	@echo "── Restarting container to pick up new image ──"
	az container restart --resource-group $(RESOURCE_GROUP) --name remy
	@echo "── Done. Use 'make deploy-logs' to watch startup ──"

# Stream live container logs
deploy-logs:
	az container logs --resource-group $(RESOURCE_GROUP) --name remy --follow

# Show container status and IP
deploy-status:
	@az container show \
		--resource-group $(RESOURCE_GROUP) \
		--name remy \
		--query "{state:instanceView.state, ip:ipAddress.ip, fqdn:ipAddress.fqdn}" \
		--output table

# Delete the container (preserves storage — data safe)
deploy-delete:
	az container delete --resource-group $(RESOURCE_GROUP) --name remy --yes
