"""Things that can go wrong while paying, in the language of the shop.

Each error carries the machine-readable code and the HTTP status the API
answers with, so the rules live next to the domain and the HTTP layer only has
to translate.
"""

from __future__ import annotations

from typing import Any


class PaymentError(Exception):
    """Base class for every refusal to start or finish a payment."""

    code = "payment_error"
    http_status = 400

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class CartNotFound(PaymentError):
    """No such cart, or it is not this user's cart.

    The two are answered the same way on purpose: telling a caller that a cart
    exists but belongs to someone else leaks other people's data.
    """

    code = "cart_not_found"
    http_status = 404


class CartNotPayable(PaymentError):
    """The cart was abandoned, or has already been checked out."""

    code = "cart_not_payable"
    http_status = 409


class CartEmpty(PaymentError):
    code = "cart_empty"
    http_status = 422


class MixedCurrencies(PaymentError):
    """One charge cannot be made in two currencies."""

    code = "mixed_currencies"
    http_status = 422


class PaymentMethodNotFound(PaymentError):
    """The user has no saved card, or not the one that was asked for."""

    code = "payment_method_not_found"
    http_status = 422


class PaymentAlreadyInProgress(PaymentError):
    """Another payment for this cart is still waiting on the provider."""

    code = "payment_already_in_progress"
    http_status = 409


class CartAlreadyPaid(PaymentError):
    code = "cart_already_paid"
    http_status = 409


class OutOfStock(PaymentError):
    """The shop cannot ship what the cart asks for, so it will not charge."""

    code = "out_of_stock"
    http_status = 409


class IdempotencyKeyReused(PaymentError):
    """The key was already used for a different request.

    Answering with the earlier cart's payment would be wrong, and charging the
    new cart would break the promise the key stands for. So: refuse.
    """

    code = "idempotency_key_reused"
    http_status = 422


class ProviderUnavailable(PaymentError):
    """We could not find out whether the card was charged.

    The payment stays in flight. Repeating the request with the same
    idempotency key asks the provider again and settles it.
    """

    code = "provider_unavailable"
    http_status = 502
