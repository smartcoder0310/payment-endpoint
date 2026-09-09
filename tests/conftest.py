"""Test setup.

The tests run against a real PostgreSQL database. The payment code leans on
things only a real database does -- row locks, a partial unique index, NUMERIC
arithmetic -- and a test that swapped in SQLite would be testing something other
than what runs in production.

The database named by TEST_DATABASE_URL is dropped and rebuilt from migrations/
at the start of every run, so it must not be a database with anything in it.
"""

from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv
from sqlalchemy import text

from app import create_app
from app.config import Config
from app.db_schema import apply_migrations, drop_everything
from app.extensions import db
from app.providers import MockPaymentProvider

load_dotenv()

_TABLES_TO_EMPTY = (
    "payment_events",
    "payments",
    "cart_items",
    "carts",
    "user_payment_methods",
    "products",
    "users",
)


@pytest.fixture(scope="session")
def app():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "TEST_DATABASE_URL is not set. See README.md for how to start a "
            "PostgreSQL database for the tests."
        )

    app = create_app(Config(database_url=database_url))
    with app.app_context():
        drop_everything(db.engine)
        apply_migrations(db.engine)
        yield app


@pytest.fixture(autouse=True)
def clean_database(app):
    """Give every test an empty database to start from."""
    with app.app_context():
        db.session.execute(
            text(f"TRUNCATE {', '.join(_TABLES_TO_EMPTY)} RESTART IDENTITY CASCADE")
        )
        db.session.commit()
        yield


@pytest.fixture
def provider(app) -> MockPaymentProvider:
    provider = MockPaymentProvider()
    app.extensions["payment_provider"] = provider
    return provider


@pytest.fixture
def client(app, provider):
    with app.app_context():
        yield app.test_client()


@pytest.fixture
def pay(client):
    """POST a payment for a cart, the way a client would.

    A fresh idempotency key is used unless the test names one, so a test that is
    not about idempotency does not have to think about it.
    """

    def _pay(cart, user, *, idempotency_key=None, **body):
        return client.post(
            f"/api/v1/carts/{_id(cart)}/payments",
            headers={
                "X-User-Id": str(_id(user)),
                "Idempotency-Key": idempotency_key or uuid.uuid4().hex,
            },
            json=body,
        )

    return _pay


@pytest.fixture
def session(app):
    """The session the test itself reads and writes with.

    It is the same session the endpoint uses, so a test must expire what it
    holds before re-reading rows the endpoint has changed. `reload` below does
    that; the tests call it rather than trusting stale objects.
    """
    with app.app_context():
        yield db.session


def reload(session, instance):
    """Read an object again, as the database now has it."""
    session.expire_all()
    return session.get(type(instance), instance.id)


def _id(value):
    """Accept either a model or a bare id, so tests can pass whichever they hold."""
    return getattr(value, "id", value)
