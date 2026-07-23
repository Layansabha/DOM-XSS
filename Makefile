TF_HETZNER_DIR := infra/terraform
TF_LOCAL_DIR := infra/terraform/local

.PHONY: up down logs build test lint typecheck audit \
	tf-fmt tf-validate tf-test \
	tf-local-plan tf-local-apply tf-local-output tf-local-destroy

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
	terraform fmt -recursive infra/terraform

tf-validate:
	terraform -chdir=$(TF_HETZNER_DIR) init -backend=false
	terraform -chdir=$(TF_HETZNER_DIR) validate
	terraform -chdir=$(TF_LOCAL_DIR) init -backend=false
	terraform -chdir=$(TF_LOCAL_DIR) validate

tf-test:
	terraform -chdir=$(TF_HETZNER_DIR) test
	terraform -chdir=$(TF_LOCAL_DIR) test

tf-local-plan:
	terraform -chdir=$(TF_LOCAL_DIR) init -backend=false
	terraform -chdir=$(TF_LOCAL_DIR) plan

tf-local-apply:
	terraform -chdir=$(TF_LOCAL_DIR) init -backend=false
	terraform -chdir=$(TF_LOCAL_DIR) apply

tf-local-output:
	terraform -chdir=$(TF_LOCAL_DIR) output

tf-local-destroy:
	terraform -chdir=$(TF_LOCAL_DIR) destroy
