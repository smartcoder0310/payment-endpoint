"""Applying the SQL files in migrations/ to a database.

A very small migration runner, on purpose. The schema is written as plain SQL --
that is the deliverable, and it should be readable as itself rather than as
generated Python -- so all that is needed is something that applies each file
once, in order, and remembers that it did.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"
SEEDS_DIR = PROJECT_ROOT / "seeds"

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT        PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def apply_migrations(engine: Engine) -> list[str]:
    """Run every migration that has not run yet. Returns the ones applied.

    Each migration runs in its own transaction together with the row that
    records it, so a migration is never half-applied and never applied twice.
    """
    with engine.begin() as connection:
        connection.execute(text(_CREATE_MIGRATIONS_TABLE))
        applied = set(connection.scalars(text("SELECT version FROM schema_migrations")))

    newly_applied = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        if version in applied:
            continue
        with engine.begin() as connection:
            connection.execute(text(path.read_text(encoding="utf-8")))
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": version},
            )
        newly_applied.append(version)

    return newly_applied


def run_sql_file(engine: Engine, path: Path) -> None:
    with engine.begin() as connection:
        connection.execute(text(path.read_text(encoding="utf-8")))


def drop_everything(engine: Engine) -> None:
    """Empty the database completely. For development and tests only."""
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
