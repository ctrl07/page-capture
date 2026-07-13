.PHONY: dev lint typecheck test format install

dev:
	uv sync
	uv run streamlit run app.py

install:
	uv sync

lint:
	uv run ruff check .

typecheck:
	uv run pyright

test:
	uv run pytest -q

format:
	uv run ruff format .
	uv run ruff check --fix .
