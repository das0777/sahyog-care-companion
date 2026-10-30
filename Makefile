.PHONY: help up down reset migrate seed test lint fmt token eval eval-live redflag scrub llm-smoke chat desk purge-threads set-key key-from-clipboard w2-samples upload doc-status search ask logs psql

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

eval:  ## Offline safety and W1 path evals on the fake model; GUARDRAILS=off must fail
	$(EXEC) python -m sahyog.evals.run --guardrails $(or $(GUARDRAILS),on) $(if $(W2_SEED),--w2-seed $(W2_SEED))

redflag:  ## Red-flag gate on one message: make redflag text="..." [age=62]
	@$(EXEC) python -m sahyog.cli redflag --text "$(text)" $(if $(age),--age $(age))

scrub:  ## What leaves the boundary: make scrub text="..." [patient=P0001]
	@$(EXEC) python -m sahyog.cli scrub --text "$(text)" $(if $(patient),--patient $(patient))

llm-smoke:  ## One real model call (needs a key: make set-key)
	@$(EXEC) python -m sahyog.cli llm-smoke

eval-live:  ## Real model calls (costs money): set=tune|match|speed|probe3|heldout|ask-tune|ask-freeze|ask|ask-redteam|ask-speed
	$(EXEC) python -m $(if $(findstring ask,$(set)),sahyog.evals.w2_live,sahyog.evals.w1_live) --set $(set)

chat:  ## A whole W1 conversation in the terminal: make chat patient=P0001
	@docker compose exec api python -m sahyog.cli chat --patient $(patient)

desk:  ## Print the front-desk queue
	@$(EXEC) python -m sahyog.cli desk

purge-threads:  ## Delete W1 thread state past its 30-day expiry
	@$(EXEC) python -m sahyog.cli purge-threads

set-key:  ## Save your model API key to .env without showing it, then restart the API
	@python3 scripts/set_key.py
	@docker compose up -d --wait api

key-from-clipboard:  ## Same as set-key, using the key you copied
	@python3 scripts/set_key.py --clipboard
	@docker compose up -d --wait api

upload:  ## Upload a PDF as a patient: make upload file=path/to/report.pdf patient=P0001
	@curl -s -X POST localhost:8000/w2/documents \
		-H "Authorization: Bearer $$($(EXEC) python -m sahyog.cli token --role patient --id $(patient))" \
		-H "Idempotency-Key: $$(uuidgen)" -F "file=@$(file);type=application/pdf"; echo

doc-status:  ## Status of an upload: make doc-status job=<job_id> patient=P0001
	@curl -s localhost:8000/w2/documents/$(job) \
		-H "Authorization: Bearer $$($(EXEC) python -m sahyog.cli token --role patient --id $(patient))"; echo

ask:  ## Ask about reports: make ask patient=P0011 q="my HbA1c?" [as=CG0011]
	@$(EXEC) python -m sahyog.cli ask --patient $(patient) --q "$(q)" $(if $(as),--as $(as))

search:  ## Search a patient's records: make search patient=P0001 q="HbA1c"
	@$(EXEC) python -m sahyog.cli search --patient $(patient) --q "$(q)"

w2-samples:  ## Generate the synthetic report PDFs and their truth file
	@$(EXEC) python -m sahyog.evals.w2_samples

logs:  ## Follow API logs
	docker compose logs -f api

psql:  ## Open psql on the dev database
	docker compose exec postgres psql -U sahyog -d sahyog
