.PHONY: install install-dev test lint typecheck run-tui help

help:
	@echo "Targets:"
	@echo "  install      uv sync (core deps)"
	@echo "  install-dev  uv sync --extra dev"
	@echo "  test         run pytest"
	@echo "  lint         ruff check"
	@echo "  typecheck    mypy"
	@echo "  run-tui      launch Textual TUI"

install:
	uv sync

install-dev:
	uv sync --extra dev

test:
	uv run pytest -q

lint:
	uv run ruff check src tests

typecheck:
	uv run mypy src/reproagent

run-tui:
	uv run reproagent tui
