.PHONY: validate ollama-check model-run builder-run foundry-run a2a-submit traces zoo test docker-run docker-reset

validate:
	python -m src.builder --config configs/example-tasks/research.yaml --validate-only

ollama-check:
	python -m src.graph --check

model-run:
	python -m src.graph

builder-run:
	python -m src.builder --config configs/example-tasks/research.yaml

foundry-run:
	python -m src --config configs/example-tasks/research.yaml

a2a-submit:
	python -m src.a2a --config configs/example-tasks/research.yaml

traces:
	tail -f data/traces.jsonl

zoo:
	@echo http://localhost:8080

test:
	python -m pytest

docker-run:
	docker compose up --build

docker-reset:
	docker compose down --rmi local --remove-orphans
	docker compose build --no-cache
