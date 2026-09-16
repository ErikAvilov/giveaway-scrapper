# Giveaway collector

Python collector that discovers giveaways via lightweight HTTP crawling (Scrapling),
enriches them with Gemini, and stores results in Neon PostgreSQL.

Designed for a **Raspberry Pi 5 (ARM64, 2 GB RAM)**: no local LLM, no Chromium.

## Requirements

- Python 3.12+
- Neon PostgreSQL (**pooled** connection string)
- Gemini API key (**only** for `analyze` / `pipeline` / `worker` — not for `db-init`, `crawl`, `stats`, or `health`)

## Setup (local / Pi without Docker)

```bash
cd collector
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Edit .env — never commit secrets
python -m app.cli db-init
python -m app.cli seed-sources config/sources.example.json
```

## CLI

```bash
python -m app.cli db-init
python -m app.cli seed                 # real French aggregators (sources.real.json)
python -m app.cli seed --examples      # optional smoke fixtures
python -m app.cli seed-sources config/sources.example.json
python -m app.cli crawl --dry-run
python -m app.cli crawl --real-test --dry-run   # first live experiment (no Gemini)
python -m app.cli analyze --limit 20
python -m app.cli pipeline --limit 50   # hard cap: ≤50 Gemini calls
python -m app.cli stats
python -m app.cli health
python -m app.cli worker          # continuous scheduler
```

### First real-source dry-run

```bash
python -m app.cli db-init
python -m app.cli seed
python -m app.cli crawl --real-test --dry-run
```

`--real-test` forces: max 10 pages/source, depth 1, concurrency 2/1, AutoThrottle on,
diagnostics on, **no Gemini**. Only sources with `crawl_config.profile=real` are crawled.

### Worker behaviour

`worker` loops forever:

1. Query Neon for enabled sources with `next_crawl_at <= now`
2. Take a Postgres advisory lock (one crawl batch at a time)
3. Crawl due sources sequentially
4. On crawl failure, schedule exponential backoff (15m → 30m → 60m → … capped at 6h)
5. Analyze new/changed candidates (bounded batch; leftover rows stay pending)
6. Sleep when idle; backoff on network errors
7. Handle SIGTERM/SIGINT cleanly and refresh a heartbeat file

## Raspberry Pi 5 — Docker deployment

On the Pi (ARM64), from `collector/`:

```bash
cp .env.example .env
# fill DATABASE_URL; add GEMINI_API_KEY + GEMINI_MODEL for analysis

docker compose up -d --build
docker compose logs -f
docker compose restart
docker compose down
```

Useful one-offs:

```bash
docker compose exec collector python -m app.cli stats
docker compose exec collector python -m app.cli health
docker compose exec collector python -m app.cli seed-sources config/sources.example.json
```

### Compose defaults (Pi-safe)

| Setting | Value |
|---------|--------|
| Memory limit | **768 MB** (leaves headroom on 2 GB RAM) |
| Restart | `unless-stopped` |
| User | non-root `collector` |
| Ports | none published |
| Browsers | **not** installed |
| Persist volumes | none (Neon is source of truth) |
| Concurrency | 2 global / 1 per domain |

Image notes:

- `python:3.12-slim-bookworm` multi-stage build
- No GUI, no Chromium/`scrapling install`
- Playwright **Python packages** may still be present as Scrapling import deps, but browser binaries are never downloaded

## Environment

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Neon pooled Postgres URL |
| `GEMINI_API_KEY` | Gemini API key (optional for crawl/db/stats/health) |
| `GEMINI_MODEL` | Model id (default `gemini-3.5-flash-lite`) |
| `GEMINI_BATCH_SIZE` | Max giveaways per `generate_content` call (default 10) |
| `GEMINI_MAX_REQUESTS_PER_MINUTE` | Process-level API RPM cap (default 6) |
| `LOG_LEVEL` | `INFO` by default |
| `WORKER_IDLE_SLEEP_SECONDS` | Sleep when nothing due (default 60) |
| `WORKER_ERROR_SLEEP_SECONDS` | Base backoff on errors (default 30) |
| `WORKER_ANALYZE_LIMIT` | Max Gemini jobs per tick (default 25) |
| `CRAWL_*` | Concurrency, depth, pages, delays |

## Memory posture (2 GB Pi)

- One crawl batch at a time (advisory lock)
- Low HTTP concurrency; AutoThrottle
- Truncated `raw_excerpt`; candidate payloads cleared after persistence (dry-run keeps them for display)
- `gc.collect()` after each worker tick
- Container `mem_limit: 768m` so a leak cannot eat the whole Pi

## Safe project archive (Linux / WSL)

Never archive secrets or build artifacts. From the parent of the repo:

```bash
tar --exclude='.env' \
    --exclude='.env.*' \
    --exclude='.env.local' \
    --exclude='node_modules' \
    --exclude='.next' \
    --exclude='.venv' \
    --exclude='**/__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='.ruff_cache' \
    --exclude='*.tsbuildinfo' \
    --exclude='collector/config/sources.local.json' \
    --exclude='.git' \
    -czvf giveaway-scrapper-safe.tgz giveaway-scrapper
```

Do not print or log API keys / database URLs. Secrets stay in local `.env` files (gitignored).

## Verify

```bash
ruff check
pytest -q
python -m app.cli --help
python -m app.cli stats
```
