# giveaway-scrapper

Personal giveaway discovery system.

## Architecture

| Component | Role |
|-----------|------|
| **Raspberry Pi 5** (`collector/`) | Python crawler + Gemini analysis, writes to Neon |
| **Desktop PC** (`dashboard/`) | Next.js UI, reads from Neon |
| **Neon PostgreSQL** | Single source of truth — Pi and dashboard never talk directly |

## Repository layout

```
collector/   # Python scraper / analyzer (Pi)
dashboard/   # Next.js dashboard (desktop)
```

## Status

- **Collector**: crawler + Gemini analysis + continuous `worker` (Pi / Docker)
- **Dashboard**: Next.js admin UI on the desktop PC (`dashboard/`)

See [`collector/README.md`](collector/README.md) for setup, CLI, and a **safe archive** command that excludes `.env` / `node_modules` / `.venv` / etc.

Default Gemini model: `gemini-3.5-flash-lite` (override with `GEMINI_MODEL`).
