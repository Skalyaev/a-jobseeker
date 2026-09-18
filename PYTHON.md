# Python rules

## Structure

- Extension points (scrapers, AI backends, outputs, templates): an ABC subclass registered in a `Registry`.
- Each implementation reads its own settings model from `<section>.<name>`. Never branch on implementation names.
- File locations come from `AppDirs` (config / data / cache, each overridable by CLI option).
- Never hardcode paths or write to the working directory.
- Build and validate every component before any network or AI call.

## Typing

- Full typing, `mypy --strict` clean.
- `Any` only for free-form JSON.
- No untyped dict as a return value: use a dataclass or a pydantic model.
- Mutable defaults via `Field(default_factory=...)`.

## Validation

- Validate external input (config, files, AI answers) with pydantic models (`extra="forbid"`).
- A model is the single source of truth for its JSON schema.

## Errors

- Raise `JobseekerError` subclasses, with a message stating what to fix.
- No bare `except`.

## Imports

- Absolute imports (`from a_jobseeker...`).

## Comments

- Google-style docstring on every public module-level function, class and public method.
- `Raises:` section when the callable raises.
- Private helpers only when non-obvious.
- Comments explain why, not what.
- English only in code: identifiers, comments, docstrings, logs, errors, CLI text.
- Translations live in data files (`templates/locales/*.json`).

## Performance

- Send the AI compact JSON, and keep the prompt prefix identical across requests (prompt cache).
- Skip offers (duplicates, filters) before any detail download or AI call.

## Workflow

- Tests cover 100% of lines and branches; remove unreachable code rather than excluding it.
- Before finishing: `make check` (format, ruff, mypy, pytest with coverage).
