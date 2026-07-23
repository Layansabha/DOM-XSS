.PHONY: up down logs build test lint typecheck audit tf-fmt tf-validate tf-test

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

build:
	docker compose build --pull

test:
	pytest

lint:
	ruff check .

typecheck:
	mypy app

audit:
	pip-audit

tf-fmt:
	terraform -chdir=infra/terraform fmt -recursive

tf-validate:
	terraform -chdir=infra/terraform init -backend=false
	terraform -chdir=infra/terraform validate

tf-test:
	terraform -chdir=infra/terraform test
