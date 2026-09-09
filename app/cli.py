"""Command line helpers, for setting up a database to run against."""

from __future__ import annotations

import click
from flask import Flask

from app.db_schema import SEEDS_DIR, apply_migrations, drop_everything, run_sql_file
from app.extensions import db


def register_commands(app: Flask) -> None:
    @app.cli.command("db-upgrade")
    def db_upgrade() -> None:
        """Apply every migration that has not been applied yet."""
        applied = apply_migrations(db.engine)
        for version in applied:
            click.echo(f"applied {version}")
        if not applied:
            click.echo("the database is already up to date")

    @app.cli.command("db-seed")
    def db_seed() -> None:
        """Load the sample shop data that came with the task."""
        run_sql_file(db.engine, SEEDS_DIR / "sample_data.sql")
        click.echo("loaded seeds/sample_data.sql")

    @app.cli.command("db-reset")
    def db_reset() -> None:
        """Throw the database away and build it again. Development only."""
        drop_everything(db.engine)
        apply_migrations(db.engine)
        click.echo("the database was rebuilt from migrations/")
