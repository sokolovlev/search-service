COMPOSE ?= docker compose

.DEFAULT_GOAL := help
.PHONY: help up load reload reindex test openapi logs down clean

help: ## список команд
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-9s %s\n", $$1, $$2}'

up: ## собрать образы и запустить сервис (API на http://localhost:8000)
	$(COMPOSE) up -d --build

load: ## скачать датасет (если его нет в data/) и загрузить в PostgreSQL и Elasticsearch
	$(COMPOSE) run --rm loader --download

reload: ## удалить все документы и загрузить датасет заново
	$(COMPOSE) run --rm loader --download --recreate

reindex: ## пересобрать индекс Elasticsearch по данным из PostgreSQL
	$(COMPOSE) run --rm loader --reindex

test: ## запустить функциональные тесты в Docker
	$(COMPOSE) build tests
	$(COMPOSE) run --rm tests

openapi: ## перегенерировать docs.json из кода
	$(COMPOSE) build app
	$(COMPOSE) run --rm --no-deps -T app python -m app.openapi > docs.json.tmp && mv docs.json.tmp docs.json

logs: ## логи приложения
	$(COMPOSE) logs -f app

down: ## остановить контейнеры
	$(COMPOSE) down

clean: ## остановить контейнеры и удалить данные
	$(COMPOSE) down -v
