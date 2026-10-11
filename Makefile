# Hachi development entry points. `make` sets up, regenerates contracts and runs every check.

.PHONY: all build check setup schema types fixtures lint test contracts-check

all: setup build check

# Regenerate the JSON Schema, TypeScript types and synthetic fixtures from src/hachi/contracts.
build: schema types fixtures

# Everything CI runs: lint, tests, and proof that generated files match their source.
check: lint test contracts-check

setup:
	uv sync --locked
	cd contracts && bun install --frozen-lockfile

schema:
	uv run python -m hachi.contracts.schema

types: schema
	cd contracts && bun run generate

fixtures:
	uv run python contracts/scripts/build_fixtures.py

# Lint covers the package, contracts and the tracked script folders that are clean. Not
# scripts/coordination (local inbox helpers live there untracked) or scripts/gx10 (it runs in the
# GX10's own Python and is not yet clean). List folders explicitly; never lint all of scripts/.
LINT_PATHS := src tests contracts scripts/rehearsal scripts/privacy scripts/evaluation

lint:
	uv run ruff check $(LINT_PATHS)
	uv run ruff format --check $(LINT_PATHS)

test:
	uv run pytest
	cd scripts/coordination && uv run python -m unittest -q

contracts-check:
	uv run python -m hachi.contracts.schema --check
	uv run python contracts/scripts/build_fixtures.py --check
	cd contracts && bun run check
