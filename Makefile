.PHONY: up down logs test unit probe verify
up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api worker

unit:
	python -m pytest -q tests/test_unit.py

test:
	python -m pytest -q tests

probe:
	python scripts/concurrency_probe.py --base http://localhost:8080

verify:
	docker compose exec -T postgres psql -U tickets -d tickets -f /dev/stdin < scripts/invariants.sql
