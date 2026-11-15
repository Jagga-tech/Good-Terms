.PHONY: dev test smoke frozen live coco

dev:
	@sh -c 'trap "kill 0" EXIT; uv run --env-file .env uvicorn api.main:app --reload --port 8000 & npm --prefix web run dev'

test:
	uv run pytest -q
	uv run python -m scripts.dump_web_data
	npm --prefix web test

smoke:
	python3 scripts/smoke.py

frozen:
	uv run --env-file .env python -m scripts.m3_frozen

live:
	uv run --env-file .env python -m scripts.m3_live

coco:
	uv run --env-file .env python -m scripts.m5_coco
