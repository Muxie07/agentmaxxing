.PHONY: test lint demo study

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

demo:
	@echo "make demo is built in M5; not implemented yet." && exit 1

study:
	@echo "make study is built in M4; not implemented yet." && exit 1
