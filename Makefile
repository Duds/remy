.PHONY: run test test-cov lint build docker-run docker-stop setup db db-init \
        deploy deploy-update deploy-logs deploy-delete health

# ── Local development ─────────────────────────────────────────────────────────
run:
	python3 -m drbot.main

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

test:
	python3 -m pytest tests/ -v

test-cov:
	python3 -m pytest tests/ -v --cov=drbot --cov-report=term-missing

lint:
	python3 -m ruff check drbot/ tests/
	python3 -m mypy drbot/ --ignore-missing-imports

# ── Datasette (local DB browser) ──────────────────────────────────────────────
db-init:
	mkdir -p data
	python3 scripts/init_db.py

db: db-init
	python3 -m datasette serve data/drbot.db --metadata config/datasette.yml --open

# ── Docker (local) ────────────────────────────────────────────────────────────
build:
	docker build -t drbot:latest .

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
		echo "Health check failed — is drbot running?"

# ── Azure deployment ──────────────────────────────────────────────────────────
# Required env vars (set in shell or .env.azure):
#   ACR_NAME          — Azure Container Registry name (e.g. myacr)
#   RESOURCE_GROUP    — Azure resource group
#   STORAGE_ACCOUNT   — Azure Storage Account name (for SQLite persistence)
#   STORAGE_KEY       — Azure Storage Account key
#   STORAGE_SHARE     — Azure File Share name (e.g. drbot-data)
#   TELEGRAM_BOT_TOKEN
#   ANTHROPIC_API_KEY

# Push image to ACR then create/replace the container instance
deploy: build
	@echo "── Pushing image to ACR: $(ACR_NAME) ──"
	az acr login --name $(ACR_NAME)
	docker tag drbot:latest $(ACR_NAME).azurecr.io/drbot:latest
	docker push $(ACR_NAME).azurecr.io/drbot:latest

	@echo "── Creating Azure Container Instance ──"
	az container create \
		--resource-group $(RESOURCE_GROUP) \
		--name drbot \
		--image $(ACR_NAME).azurecr.io/drbot:latest \
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
	docker tag drbot:latest $(ACR_NAME).azurecr.io/drbot:latest
	docker push $(ACR_NAME).azurecr.io/drbot:latest
	@echo "── Restarting container to pick up new image ──"
	az container restart --resource-group $(RESOURCE_GROUP) --name drbot
	@echo "── Done. Use 'make deploy-logs' to watch startup ──"

# Stream live container logs
deploy-logs:
	az container logs --resource-group $(RESOURCE_GROUP) --name drbot --follow

# Show container status and IP
deploy-status:
	@az container show \
		--resource-group $(RESOURCE_GROUP) \
		--name drbot \
		--query "{state:instanceView.state, ip:ipAddress.ip, fqdn:ipAddress.fqdn}" \
		--output table

# Delete the container (preserves storage — data safe)
deploy-delete:
	az container delete --resource-group $(RESOURCE_GROUP) --name drbot --yes
