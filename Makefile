TF_DIR := infra/terraform
BASE_COMPOSE := docker compose -f compose.yaml
ZAP_COMPOSE := $(BASE_COMPOSE) -f deploy/compose/zap.yaml
MONITOR_COMPOSE := $(BASE_COMPOSE) -f deploy/compose/observability.yaml
MONITOR_ZAP_COMPOSE := $(ZAP_COMPOSE) -f deploy/compose/observability.yaml
E2E_COMPOSE := docker compose -f compose.yaml -f deploy/compose/e2e.yaml

.PHONY: up up-zap down logs build monitor-up monitor-up-zap e2e \
	test lint typecheck audit benchmark tf-fmt tf-validate tf-test

up:
	$(BASE_COMPOSE) up --build --remove-orphans

up-zap:
	$(ZAP_COMPOSE) up --build --remove-orphans

down:
	$(MONITOR_ZAP_COMPOSE) down --remove-orphans

logs:
	$(MONITOR_ZAP_COMPOSE) logs -f --tail=200

build:
	$(BASE_COMPOSE) build --pull

monitor-up:
	$(MONITOR_COMPOSE) up --build -d --remove-orphans

monitor-up-zap:
	$(MONITOR_ZAP_COMPOSE) up --build -d --remove-orphans

e2e:
	@test -f .env || cp .env.example .env
	@set -eu; \
		cleanup() { $(E2E_COMPOSE) down --volumes --remove-orphans; }; \
		trap cleanup EXIT INT TERM; \
		$(E2E_COMPOSE) up --build -d --wait; \
		python3 scripts/e2e_smoke.py

test:
	pytest

lint:
	ruff check .

typecheck:
	mypy app

audit:
	pip-audit

benchmark:
	@test -f artifacts/lightgbm_grouped_model.txt || \
		ARTIFACT_DIR="$(CURDIR)/artifacts" python scripts/prepare_artifacts.py
	ML_MODEL_PATH="$(CURDIR)/artifacts/lightgbm_grouped_model.txt" \
		ML_VOCAB_PATH="$(CURDIR)/artifacts/vocab_top500_grouped.json" \
		python scripts/benchmark_pages.py

tf-fmt:
	terraform fmt -recursive $(TF_DIR)

tf-validate:
	terraform -chdir=$(TF_DIR) init -backend=false
	terraform -chdir=$(TF_DIR) validate

tf-test:
	terraform -chdir=$(TF_DIR) test
