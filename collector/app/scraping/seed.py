"""Seed sources from a JSON config file into Neon."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from psycopg import Connection

from app.db.repository import SourceRepository
from app.models.source import Source, SourceType

logger = logging.getLogger(__name__)


def load_sources_file(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        sources = data.get("sources")
    else:
        sources = data
    if not isinstance(sources, list):
        raise TypeError("Sources file must contain a top-level 'sources' array")
    return sources


def seed_sources(conn: Connection, path: Path) -> list[Source]:
    repo = SourceRepository(conn)
    seeded: list[Source] = []
    for raw in load_sources_file(path):
        source = repo.upsert_by_base_url(
            name=str(raw["name"]),
            base_url=str(raw["base_url"]),
            source_type=SourceType(str(raw.get("source_type", "other"))),
            enabled=bool(raw.get("enabled", True)),
            crawl_interval_minutes=int(raw.get("crawl_interval_minutes", 60)),
            crawl_config=dict(raw.get("crawl_config") or {}),
        )
        seeded.append(source)
        logger.info(
            "seeded source id=%s name=%s enabled=%s",
            source.id,
            source.name,
            source.enabled,
        )
    return seeded
