"""Apply SQL migrations safely (never drops existing data)."""

from __future__ import annotations

import logging
from pathlib import Path

from psycopg import Connection

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def migrations_dir() -> Path:
    return MIGRATIONS_DIR


def ensure_migrations_table(conn: Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def list_migration_files(directory: Path | None = None) -> list[Path]:
    root = directory or migrations_dir()
    if not root.is_dir():
        raise FileNotFoundError(f"Migrations directory not found: {root}")
    return sorted(p for p in root.glob("*.sql") if p.is_file())


def applied_migrations(conn: Connection) -> set[str]:
    rows = conn.execute("SELECT filename FROM schema_migrations").fetchall()
    return {row["filename"] for row in rows}


def apply_migrations(conn: Connection, directory: Path | None = None) -> list[str]:
    """
    Apply pending *.sql files in lexicographic order.

    Each file runs in its own transaction. Already-applied files are skipped.
    SQL files must be additive (CREATE IF NOT EXISTS); they must not DROP data.
    """
    ensure_migrations_table(conn)
    conn.commit()

    pending_applied: list[str] = []
    already = applied_migrations(conn)
    files = list_migration_files(directory)

    for path in files:
        name = path.name
        if name in already:
            logger.info("migration skip filename=%s", name)
            continue

        sql_text = path.read_text(encoding="utf-8")
        logger.info("migration apply filename=%s", name)
        try:
            conn.execute(sql_text)
            conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)",
                (name,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("migration failed filename=%s", name)
            raise

        pending_applied.append(name)
        logger.info("migration ok filename=%s", name)

    return pending_applied


def migration_status(conn: Connection, directory: Path | None = None) -> dict[str, bool]:
    """Map migration filename -> whether it has been applied."""
    ensure_migrations_table(conn)
    already = applied_migrations(conn)
    return {path.name: path.name in already for path in list_migration_files(directory)}
