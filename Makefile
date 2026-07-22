.PHONY: up down logs build test lint typecheck audit

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
