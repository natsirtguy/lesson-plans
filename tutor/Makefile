SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend
VENV := $(BACKEND)/.venv
PY := $(VENV)/bin/python
PIP := uv pip install --python $(VENV)/bin/python

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(VENV)/bin/python:
	cd $(BACKEND) && uv venv --python 3.12
	$(PIP) -e "$(BACKEND)[dev]"

.PHONY: install
install: $(VENV)/bin/python ## Create the venv and install backend + frontend deps
	cd $(FRONTEND) && npm install

.PHONY: dev
dev: install ## Run backend on :8000 and frontend on :5173
	@trap 'kill 0' EXIT INT TERM; \
	( cd $(BACKEND) && ../$(VENV)/bin/uvicorn app.main:app --reload --port 8000 ) & \
	( cd $(FRONTEND) && npm run dev ) & \
	wait

.PHONY: backend
backend: $(VENV)/bin/python ## Run only the backend
	cd $(BACKEND) && ../$(VENV)/bin/uvicorn app.main:app --reload --port 8000

.PHONY: frontend
frontend: ## Run only the frontend
	cd $(FRONTEND) && npm run dev

.PHONY: migrate
migrate: $(VENV)/bin/python ## Apply database migrations
	cd $(BACKEND) && ../$(VENV)/bin/alembic upgrade head

.PHONY: revision
revision: $(VENV)/bin/python ## Autogenerate a migration: make revision m="message"
	cd $(BACKEND) && ../$(VENV)/bin/alembic revision --autogenerate -m "$(m)"

.PHONY: lint
lint: $(VENV)/bin/python ## ruff check + format check
	cd $(BACKEND) && ../$(VENV)/bin/ruff check app tests
	cd $(BACKEND) && ../$(VENV)/bin/ruff format --check app tests

.PHONY: format
format: $(VENV)/bin/python ## Apply ruff formatting
	cd $(BACKEND) && ../$(VENV)/bin/ruff format app tests
	cd $(BACKEND) && ../$(VENV)/bin/ruff check --fix app tests

.PHONY: types
types: $(VENV)/bin/python ## mypy --strict
	cd $(BACKEND) && ../$(VENV)/bin/mypy

.PHONY: test
test: $(VENV)/bin/python ## Run the backend test suite
	cd $(BACKEND) && ../$(VENV)/bin/python -m pytest -q

.PHONY: check
check: lint types test ## Everything that must pass before a commit

.PHONY: test-frontend
test-frontend: ## Run the frontend test suite
	cd $(FRONTEND) && npm test

.PHONY: check-frontend
check-frontend: ## Typecheck, test, and build the frontend
	cd $(FRONTEND) && npm run typecheck && npm test && npm run build

.PHONY: clean
clean: ## Remove build artefacts and caches
	rm -rf $(VENV) $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache
	find $(BACKEND) -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf $(FRONTEND)/node_modules $(FRONTEND)/dist
