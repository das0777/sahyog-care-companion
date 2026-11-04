.PHONY: help up down reset migrate seed test lint fmt token logs psql

EXEC = docker compose exec -T api

help:  ## List targets
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

.env:
	cp .env.example .env

up: .env  ## Build and start the stack, wait until healthy, apply migrations
	docker compose up -d --build --wait
	$(MAKE) migrate

down:  ## Stop the stack (data kept)
	docker compose down

reset:  ## Stop the stack and delete all data volumes
	docker compose down -v

migrate:  ## Apply database migrations
	$(EXEC) alembic upgrade head

seed:  ## Load deterministic synthetic data (replaces existing seed rows)
	$(EXEC) python -m sahyog.cli seed

test:  ## Run the test suite against the test database
	$(EXEC) pytest

lint:  ## Lint and format check
	$(EXEC) ruff check sahyog tests migrations
	$(EXEC) ruff format --check sahyog tests migrations

fmt:  ## Apply formatting
	$(EXEC) ruff format sahyog tests migrations
	$(EXEC) ruff check --fix sahyog tests migrations

token:  ## Issue a dev token: make token role=patient id=P0001
	@$(EXEC) python -m sahyog.cli token --role $(role) --id $(id)

logs:  ## Follow API logs
	docker compose logs -f api

psql:  ## Open psql on the dev database
	docker compose exec postgres psql -U sahyog -d sahyog
