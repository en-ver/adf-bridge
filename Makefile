.PHONY: format format-check lint type-check test docs build verify-distribution check check-ci

format:
	uv run ruff format src tests scripts

format-check:
	uv run ruff format --check src tests scripts

lint:
	uv run ruff check src tests scripts

type-check:
	uv run ty check src

test:
	uv run pytest

docs:
	uv run mkdocs build --strict

build:
	uv build

verify-distribution:
	uv run python scripts/verify_distribution.py

check: format lint type-check test

check-ci: format-check lint type-check test docs build verify-distribution
