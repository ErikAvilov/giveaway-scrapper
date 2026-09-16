SHELL := /bin/bash

COLLECTOR := collector
DASHBOARD := dashboard

PYTHON := $(COLLECTOR)/.venv/bin/python3
PIP := $(COLLECTOR)/.venv/bin/pip

LIMIT ?= 25

.PHONY: help \
	venv install init \
	db-init seed \
	purge-giveaways validate-links reset-crawl \
	reprioritize-entry \
	crawl crawl-dry crawl-real crawl-real-dry \
	analyze analyze-all pipeline worker stats health \
	test lint check \
	dashboard-install dashboard dashboard-build dashboard-check \
	docker-build docker-up docker-down docker-restart docker-logs docker-ps \
	clean

help:
	@echo ""
	@echo "giveaway-scrapper"
	@echo "================="
	@echo ""
	@echo "Installation"
	@echo "  make venv                 Crée collector/.venv"
	@echo "  make install              Installe le collector"
	@echo "  make init                 venv + install + db-init + seed"
	@echo ""
	@echo "Database / sources"
	@echo "  make db-init              Applique les migrations Neon"
	@echo "  make seed                 Ajoute/met à jour les sources"
	@echo "  make purge-giveaways      Supprime giveaways + crawl_runs (garde sources)"
	@echo "  make validate-links       Valide les entry URLs (LIMIT=50 par défaut)"
	@echo "  make validate-links LIMIT=100"
	@echo "  make reprioritize-entry   Backfill gate social public (LIMIT=500)"
	@echo "  make reset-crawl          Remet les sources enabled au prochain crawl"
	@echo ""
	@echo "Scraping"
	@echo "  make crawl                Crawl normal"
	@echo "  make crawl-dry            Crawl normal sans écriture giveaways"
	@echo "  make crawl-real           Petit crawl réel limité"
	@echo "  make crawl-real-dry       Petit crawl réel limité sans écriture"
	@echo ""
	@echo "Gemini"
	@echo "  make analyze              Analyse les pending (LIMIT=25 par défaut)"
	@echo "  make analyze LIMIT=100    Analyse max 100 giveaways"
	@echo "  make analyze-all          Analyse toute la file pending jusqu'à vide"
	@echo ""
	@echo "Pipeline"
	@echo "  make pipeline             Crawl + analyse Gemini + Neon"
	@echo "  make worker               Worker continu"
	@echo ""
	@echo "Monitoring"
	@echo "  make stats                Statistiques"
	@echo "  make health               Health check"
	@echo ""
	@echo "Tests"
	@echo "  make test                 Pytest"
	@echo "  make lint                 Ruff"
	@echo "  make check                Ruff + pytest + dashboard checks"
	@echo ""
	@echo "Dashboard"
	@echo "  make dashboard-install    npm install"
	@echo "  make dashboard            Lance le dashboard"
	@echo "  make dashboard-build      Build Next.js"
	@echo ""
	@echo "Raspberry / Docker"
	@echo "  make docker-build"
	@echo "  make docker-up"
	@echo "  make docker-down"
	@echo "  make docker-restart"
	@echo "  make docker-logs"
	@echo "  make docker-ps"
	@echo ""

# --------------------------------------------------
# Installation
# --------------------------------------------------

venv:
	python3 -m venv $(COLLECTOR)/.venv
	$(PIP) install --upgrade pip

install:
	$(PIP) install -e $(COLLECTOR)

init: venv install db-init seed
	@echo "Initialisation terminée."

# --------------------------------------------------
# Database
# --------------------------------------------------

db-init:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli db-init

seed:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli seed

# Confirmation interactive by default. Non-interactive: make purge-giveaways YES=1
purge-giveaways:
ifeq ($(YES),1)
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli purge-giveaways --yes
else
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli purge-giveaways
endif

validate-links:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli validate-links --limit $(LIMIT)

reprioritize-entry:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli reprioritize-entry --limit $(LIMIT)

reset-crawl:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli reset-crawl-schedule

# --------------------------------------------------
# Crawl
# --------------------------------------------------

crawl:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli crawl

crawl-dry:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli crawl --dry-run

crawl-real:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli crawl --real-test

crawl-real-dry:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli crawl --real-test --dry-run

# --------------------------------------------------
# Gemini analysis
# --------------------------------------------------

analyze:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli analyze --limit $(LIMIT)

analyze-all:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli analyze --all

# --------------------------------------------------
# Full pipeline / worker
# --------------------------------------------------

pipeline:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli pipeline

worker:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli worker

# --------------------------------------------------
# Monitoring
# --------------------------------------------------

stats:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli stats

health:
	cd $(COLLECTOR) && ../$(PYTHON) -m app.cli health

# --------------------------------------------------
# Python tests
# --------------------------------------------------

test:
	cd $(COLLECTOR) && .venv/bin/python3 -m pytest

lint:
	cd $(COLLECTOR) && .venv/bin/python3 -m ruff check .

# --------------------------------------------------
# Dashboard
# --------------------------------------------------

dashboard-install:
	cd $(DASHBOARD) && npm install

dashboard:
	cd $(DASHBOARD) && npm run dev

dashboard-build:
	cd $(DASHBOARD) && npm run build

dashboard-check:
	cd $(DASHBOARD) && npm run lint
	cd $(DASHBOARD) && npm run typecheck
	cd $(DASHBOARD) && npm run build

# --------------------------------------------------
# Everything
# --------------------------------------------------

check: lint test dashboard-check
	@echo "Tous les checks sont OK."

# --------------------------------------------------
# Docker / Raspberry Pi
# --------------------------------------------------

docker-build:
	cd $(COLLECTOR) && docker compose build

docker-up:
	cd $(COLLECTOR) && docker compose up -d --build

docker-down:
	cd $(COLLECTOR) && docker compose down

docker-restart:
	cd $(COLLECTOR) && docker compose restart

docker-logs:
	cd $(COLLECTOR) && docker compose logs -f

docker-ps:
	cd $(COLLECTOR) && docker compose ps

# --------------------------------------------------
# Cleanup
# --------------------------------------------------

clean:
	rm -rf $(COLLECTOR)/.pytest_cache
	rm -rf $(COLLECTOR)/.ruff_cache
	rm -rf $(DASHBOARD)/.next
	find $(COLLECTOR) -type d -name "__pycache__" -prune -exec rm -rf {} +
