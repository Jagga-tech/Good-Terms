.PHONY: dev test smoke

dev:
	@sh -c 'trap "kill 0" EXIT; uv run uvicorn api.main:app --reload --port 8000 & npm --prefix web run dev'

test:
	uv run pytest -q

smoke:
	python3 scripts/smoke.py
