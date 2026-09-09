"""One shape for every error the API returns.

    {"error": {"code": "cart_not_payable",
               "message": "A cart with status 'checked_out' cannot be paid for.",
               "details": {...}}}

`code` is for programs and never changes; `message` is for people and may.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from app.api.request_parsing import InvalidRequest
from app.services.errors import PaymentError


def error_response(
    code: str, message: str, status: int, details: dict[str, Any] | None = None, **extra: Any
):
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    body.update(extra)
    return jsonify(body), status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(InvalidRequest)
    def _invalid_request(error: InvalidRequest):
        return error_response(error.code, error.message, error.http_status, error.details)

    @app.errorhandler(PaymentError)
    def _payment_error(error: PaymentError):
        return error_response(error.code, error.message, error.http_status, error.details)

    @app.errorhandler(HTTPException)
    def _http_error(error: HTTPException):
        return error_response(
            _http_error_code(error), error.description, error.code or 500
        )

    @app.errorhandler(Exception)
    def _unexpected_error(error: Exception):
        # The details of an unexpected failure belong in the log, not in the
        # response: they are of no use to the client and may say too much.
        app.logger.exception("unhandled error while serving a request")
        return error_response(
            "internal_error", "The request could not be completed.", 500
        )


def _http_error_code(error: HTTPException) -> str:
    """'Not Found' -> 'not_found', so clients see codes rather than prose."""
    return (error.name or "error").lower().replace(" ", "_")
