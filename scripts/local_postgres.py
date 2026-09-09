"""Start a PostgreSQL for development on a machine that has none.

For local convenience only. The application targets an ordinary PostgreSQL --
see docker-compose.yml, which is the path the README describes first. This
script is for when installing one is not worth it: `pgserver` ships PostgreSQL
binaries as a Python package, so there is nothing to install system-wide, no
service, and no administrator rights needed.

    pip install pgserver
    python scripts/local_postgres.py

It starts a server under .local-postgres/, creates the `shop` and `shop_test`
databases, and writes the .env that the application and the tests read. The
server keeps running after this script exits, and the port it picked is
recorded in .env. Run it again after a reboot to start it and rewrite .env.
"""

from __future__ import annotations

import pathlib
import sys

try:
    import pgserver
except ImportError:
    sys.exit(
        "pgserver is not installed. Run `pip install pgserver`, or start a "
        "PostgreSQL another way and set DATABASE_URL yourself. See README.md."
    )

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
PGDATA = PROJECT_ROOT / ".local-postgres"
ENV_FILE = PROJECT_ROOT / ".env"

DATABASES = ("shop", "shop_test")

_ENV_TEMPLATE = """\
# Written by scripts/local_postgres.py. The port changes when the server is
# started again, so run that script rather than editing this by hand.
DATABASE_URL={url}/shop
TEST_DATABASE_URL={url}/shop_test
FLASK_APP=wsgi.py
FLASK_DEBUG=1
SQL_ECHO=0
"""


def main() -> None:
    _ensure_pgcrypto_stub()

    # cleanup_mode=None: leave the server running once this script exits, so
    # that `flask run` and `pytest` afterwards have something to talk to.
    server = pgserver.get_server(str(PGDATA), cleanup_mode=None)
    base_url, _, _ = server.get_uri().rpartition("/")
    base_url = base_url.replace("postgresql://", "postgresql+psycopg://")

    for database in DATABASES:
        if "1 row" in server.psql(
            f"SELECT 1 FROM pg_database WHERE datname = '{database}'"
        ):
            print(f"{database}: already there")
        else:
            server.psql(f"CREATE DATABASE {database}")
            print(f"{database}: created")

    ENV_FILE.write_text(_ENV_TEMPLATE.format(url=base_url), encoding="utf-8")

    print(f"\nPostgreSQL is running at {base_url}")
    print(f"Wrote {ENV_FILE.relative_to(PROJECT_ROOT)}\n")
    print("Next:  flask db-upgrade  &&  flask db-seed  &&  flask run")
    print("Tests: pytest")


def _ensure_pgcrypto_stub() -> None:
    """Let `CREATE EXTENSION pgcrypto` succeed against this bundled server.

    The base schema asks for pgcrypto, as a schema written for PostgreSQL 12 and
    earlier has to. The pgserver build ships no contrib modules, so the request
    would fail here -- even though nothing actually needs it: gen_random_uuid()
    has been part of PostgreSQL itself since version 13.

    So: an empty extension by that name, which installs nothing. It changes only
    this local server, never the schema, and a real PostgreSQL never needs it.
    """
    extensions = pathlib.Path(pgserver.__file__).parent / (
        "pginstall/share/postgresql/extension"
    )
    control = extensions / "pgcrypto.control"
    if control.exists():
        return

    control.write_text(
        "comment = 'stub: gen_random_uuid() is built into PostgreSQL 13+'\n"
        "default_version = '1.3'\n"
        "relocatable = true\n",
        encoding="utf-8",
    )
    (extensions / "pgcrypto--1.3.sql").write_text(
        "-- Nothing to install: gen_random_uuid() is in core since PostgreSQL 13.\n",
        encoding="utf-8",
    )
    print("added a stub pgcrypto extension to the bundled server")


if __name__ == "__main__":
    main()
