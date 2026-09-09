"""The Flask application factory."""

from __future__ import annotations

from flask import Flask, jsonify

from app.api.errors import register_error_handlers
from app.api.routes import api
from app.cli import register_commands
from app.config import Config
from app.extensions import db
from app.providers import MockPaymentProvider, PaymentProvider


def create_app(
    config: Config | None = None,
    payment_provider: PaymentProvider | None = None,
) -> Flask:
    """Build the application.

    Both the configuration and the payment provider are arguments so that a test
    can hand in its own without reaching into globals or patching imports.
    """
    config = config or Config.from_env()

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = config.database_url
    app.config["SQLALCHEMY_ECHO"] = config.sql_echo

    db.init_app(app)
    app.extensions["payment_provider"] = payment_provider or MockPaymentProvider()

    register_error_handlers(app)
    register_commands(app)
    app.register_blueprint(api)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    return app
