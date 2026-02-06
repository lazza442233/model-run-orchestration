.PHONY: up down build logs shell test lint

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

shell:
	docker compose exec web bash

test:
	pytest

lint:
	ruff check src
