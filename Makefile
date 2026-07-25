TF_DIR := infra/terraform

.PHONY: up down logs build monitor-up monitor-down test lint typecheck audit \
	tf-fmt tf-validate tf-test

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
