VENV ?= .venv
BIN := $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/,)

.PHONY: install fmt lint typecheck test check dist release

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

release:
	@test -n "$(VERSION)" || { echo "usage: make release VERSION=x.y.z"; exit 1; }
	@test -z "$$(git status --porcelain)" || { echo "commit your changes first"; exit 1; }
	$(MAKE) check
	sed -i -E 's/^__version__ = .*/__version__ = "$(VERSION)"/' src/a_jobseeker/__init__.py
	$(MAKE) dist
	git commit -am "Release $(VERSION)"
	git push
	gh release create "v$(VERSION)" --title "v$(VERSION)" --generate-notes
