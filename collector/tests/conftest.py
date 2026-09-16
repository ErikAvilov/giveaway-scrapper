"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from app.config import Settings, get_settings
from app.db.connection import connect
from app.db.migrate import apply_migrations


@pytest.fixture(scope="session")
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session")
def migrated_db(settings: Settings) -> None:
    """Ensure schema exists once per test session (additive migrations only)."""
    conn = connect(settings)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
