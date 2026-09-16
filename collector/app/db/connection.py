"""PostgreSQL connection helpers (psycopg 3 + Neon pooled URL)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

import psycopg
from psycopg.rows import dict_row

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


def connect(settings: Settings) -> psycopg.Connection:
    """Open a single connection using the Neon pooled DATABASE_URL."""
    url = settings.database_url.get_secret_value()
    logger.debug("Opening PostgreSQL connection")
    return psycopg.connect(url, row_factory=dict_row)


@contextmanager
def connection(settings: Settings) -> Iterator[psycopg.Connection]:
    """Context manager that commits on success and rolls back on error."""
    conn = connect(settings)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        logger.debug("Closed PostgreSQL connection")
