VENV ?= .venv
BIN := $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/,)

.PHONY: install fmt lint typecheck test check dist

install:
	$(BIN)pip install -e '.[dev]'

fmt:
	$(BIN)ruff format .
	$(BIN)ruff check --fix .

lint:
	$(BIN)ruff check .
	$(BIN)ruff format --check .

typecheck:
	$(BIN)mypy

test:
	$(BIN)pytest --cov

check: fmt lint typecheck test

dist:
	rm -rf dist
	$(BIN)python -m build
	$(BIN)twine check --strict dist/*
