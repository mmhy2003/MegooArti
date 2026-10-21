# Shortcuts for running and developing MegooArti, with GNU make.
#
# On Windows, from PowerShell, make runs each line with cmd.exe, or with sh if one is on
# the PATH: so every line here is one both understand. A command and the one after it
# go together with &&, and text is printed by make itself ($(info)), never by echo.

SERVICE ?=
ARGS ?=

.DEFAULT_GOAL := help
.PHONY: help up down ps logs reset-admin db install test test-backend test-frontend lint format

help:
	$(info The stack, under Docker Compose:)
	$(info make up                Build the images and start the stack, waiting until it is healthy)
	$(info make down              Stop the stack and remove its containers; the data stays)
	$(info make ps                What is running)
	$(info make logs              Follow the logs, of SERVICE=backend alone if it is given)
	$(info make reset-admin       Give admin a new password, end its sessions and lift sign-in blocks)
	$(info )
	$(info Development:)
	$(info make install           Install what the backend and the web UI depend on)
	$(info make db                Start the database alone, for the backend's tests)
	$(info make test              The tests of the backend and of the web UI)
	$(info make test-backend      The backend's tests, with ARGS passed on to pytest)
	$(info make test-frontend     The web UI's tests)
	$(info make lint              Lint and format checks, and the web UI's type check)
	$(info make format            Format the code of both)
	@exit 0

up:
	docker compose up --build --detach --wait

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs --follow --tail 200 $(SERVICE)

reset-admin:
	docker compose exec backend python -m megooarti.security.reset_admin

db:
	docker compose up --detach --wait db

install:
	cd backend && uv sync
	cd frontend && pnpm install

test: test-backend test-frontend

test-backend: db
	cd backend && uv run pytest $(ARGS)

test-frontend:
	cd frontend && pnpm test

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && pnpm lint && pnpm typecheck

format:
	cd backend && uv run ruff format .
	cd frontend && pnpm format
