.PHONY: build up down generate demo test start plaid

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

start: build up

generate:
	python scripts/generate_data.py --rows 100000 --accounts 1000

demo:
	time curl -s -X POST http://localhost:8000/attributes \
		-H 'Content-Type: application/json' \
		-d @data/transactions_100k.json | python -m json.tool | head -60

plaid:
	curl -s http://localhost:8000/demo/plaid | python -m json.tool

test:
	pytest -v --tb=short