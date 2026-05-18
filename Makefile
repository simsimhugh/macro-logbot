.PHONY: install run test lint format

install:
	pip install -e .[dev]

run:
	uvicorn macro_logbot.app:app --reload

test:
	pytest -v --cov=src --cov-report=term-missing

lint:
	ruff check src/
	mypy src/

format:
	ruff format src/ tests/
