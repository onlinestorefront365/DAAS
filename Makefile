.PHONY: install test migrate ingest serve up

install:
	python -m venv .venv && .venv/bin/pip install -e ".[dev]"

test:
	.venv/bin/pytest -q

migrate:
	.venv/bin/daas migrate

ingest:
	.venv/bin/daas ingest

serve:
	.venv/bin/daas serve --workers 1

up:
	docker compose up --build
