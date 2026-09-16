"""Database package: Neon PostgreSQL via psycopg 3."""

from app.db.connection import connect, connection
from app.db.migrate import apply_migrations, migration_status
from app.db.repository import (
    CrawlRunRepository,
    GiveawayRepository,
    GiveawayUpsertResult,
    SourceRepository,
)

__all__ = [
    "CrawlRunRepository",
    "GiveawayRepository",
    "GiveawayUpsertResult",
    "SourceRepository",
    "apply_migrations",
    "connect",
    "connection",
    "migration_status",
]
