"""Reading what the client sent, and refusing it early when it makes no sense.

Nothing here knows about payments. It turns an HTTP request into plain values,
or raises InvalidRequest, so that the route below reads as the payment flow and
not as a list of type checks.
"""

from __future__ import annotations

import uuid
from typing import Any

from flask import Request

_MAX_IDEMPOTENCY_KEY_LENGTH = 255


class InvalidRequest(Exception):
    """The request could not be understood. Never reaches the domain."""

    code = "invalid_request"
    http_status = 400

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


def json_body(request: Request) -> dict[str, Any]:
    """The JSON object the client sent, or an empty one if it sent no body."""
    if not request.data:
        return {}

    body = request.get_json(silent=True)
    if body is None:
        raise InvalidRequest("The request body is not valid JSON.")
    if not isinstance(body, dict):
        raise InvalidRequest("The request body must be a JSON object.")
    return body


def required_uuid_header(request: Request, name: str) -> uuid.UUID:
    value = request.headers.get(name)
    if not value:
        raise InvalidRequest(f"The {name} header is required.")
    return _to_uuid(value, name)


def required_idempotency_key(request: Request) -> str:
    """The client's promise that this request is one attempt, not two.

    It is required rather than generated: a key we make up here would be new on
    every retry, which is exactly the case it exists to protect against.
    """
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if not key:
        raise InvalidRequest(
            "The Idempotency-Key header is required. Send the same key when "
            "retrying a request, and a new key for a new payment."
        )
    if len(key) > _MAX_IDEMPOTENCY_KEY_LENGTH:
        raise InvalidRequest(
            f"The Idempotency-Key header must be at most "
            f"{_MAX_IDEMPOTENCY_KEY_LENGTH} characters."
        )
    return key


def optional_uuid_field(body: dict[str, Any], name: str) -> uuid.UUID | None:
    value = body.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidRequest(f"{name} must be a string holding a UUID.", field=name)
    return _to_uuid(value, name)


def _to_uuid(value: str, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise InvalidRequest(f"{name} is not a valid UUID.", field=name) from None
