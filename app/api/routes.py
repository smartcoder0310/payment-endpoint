"""The HTTP endpoints of the payment part."""

from __future__ import annotations

import uuid

from flask import Blueprint, current_app, jsonify, request

from app.api.errors import error_response
from app.api.request_parsing import (
    json_body,
    optional_uuid_field,
    required_idempotency_key,
    required_uuid_header,
)
from app.api.serialization import payment_to_dict
from app.extensions import db
from app.models import Payment, PaymentStatus
from app.services.payment_service import PaymentService

api = Blueprint("api", __name__, url_prefix="/api/v1")


@api.post("/carts/<uuid:cart_id>/payments")
def start_payment(cart_id: uuid.UUID):
    """Pay for a cart with the user's saved card.

    Headers:
        X-User-Id       who is paying. Stands in for real authentication.
        Idempotency-Key the client's name for this attempt. Send the same key
                        to retry, a new key to pay for something else.

    Body (optional):
        {"payment_method_id": "<uuid>"}   defaults to the user's default card.

    Answers:
        201  the card was charged
        402  the card was not charged, and why
        409  the cart is not in a state that can be paid for
        502  the provider could not be reached; retry with the same key
    """
    user_id = required_uuid_header(request, "X-User-Id")
    idempotency_key = required_idempotency_key(request)
    payment_method_id = optional_uuid_field(json_body(request), "payment_method_id")

    outcome = _payment_service().start_payment(
        user_id=user_id,
        cart_id=cart_id,
        idempotency_key=idempotency_key,
        payment_method_id=payment_method_id,
    )
    return _response_for(outcome.payment)


@api.get("/payments/<uuid:payment_id>")
def get_payment(payment_id: uuid.UUID):
    """Look up a payment, which is how a client resolves one left in flight."""
    user_id = required_uuid_header(request, "X-User-Id")
    payment = _payment_service().get_payment(user_id=user_id, payment_id=payment_id)
    if payment is None:
        return error_response("payment_not_found", "No such payment.", 404)
    return jsonify({"payment": payment_to_dict(payment)}), 200


def _response_for(payment: Payment):
    """The outcome of a payment, as a status code and a body.

    A declined card is reported as an error, because the caller asked for money
    to be taken and it was not. The payment itself is included either way: it is
    a real record with an id, and the client will want to refer to it.
    """
    body = payment_to_dict(payment)

    if payment.status == PaymentStatus.SUCCEEDED:
        return jsonify({"payment": body}), 201

    if payment.status == PaymentStatus.FAILED:
        return error_response(
            payment.failure_code,
            payment.failure_message,
            402,
            payment=body,
        )

    return jsonify({"payment": body}), 202


def _payment_service() -> PaymentService:
    return PaymentService(db.session, current_app.extensions["payment_provider"])
