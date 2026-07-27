TF_DIR := infra/terraform
E2E_COMPOSE := docker compose -f compose.yaml -f deploy/compose.e2e.yaml

.PHONY: up down logs build monitor-up monitor-down e2e e2e-down \
	test lint typecheck audit tf-fmt tf-validate tf-test

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

build:
	docker compose build --pull

monitor-up:
	docker compose -f compose.yaml -f deploy/compose.observability.yaml up --build -d

monitor-down:
	docker compose -f compose.yaml -f deploy/compose.observability.yaml down

e2e:
	@test -f .env || cp .env.example .env
	@set -eu; \
		cleanup() { $(E2E_COMPOSE) down --volumes --remove-orphans; }; \
		trap cleanup EXIT INT TERM; \
		$(E2E_COMPOSE) up --build -d --wait; \
		python3 scripts/e2e_smoke.py

e2e-down:
	$(E2E_COMPOSE) down --volumes --remove-orphans

test:
	pytest

lint:
	ruff check .

typecheck:
	mypy app

audit:
	pip-audit

tf-fmt:
	terraform fmt -recursive $(TF_DIR)

tf-validate:
	terraform -chdir=$(TF_DIR) init -backend=false
	terraform -chdir=$(TF_DIR) validate

tf-test:
	terraform -chdir=$(TF_DIR) test
