.PHONY: install run test lint format

install:
	pip install -e .[dev]

run:
	uvicorn macro_logbot.app:app --reload

test:
	pytest -v --cov

lint:
	ruff check src/
	mypy src/

format:
	black src/ tests/
	ruff format src/ tests/
