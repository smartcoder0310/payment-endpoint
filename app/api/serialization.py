"""Turning a payment into the JSON the API promises.

Amounts go out as strings. JSON numbers are floats in most clients, and a float
is the wrong shape for money: 57.50 is not exactly representable, and a cent
lost in a payment API is a bug that shows up in someone's bank statement.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.models import Payment


def payment_to_dict(payment: Payment) -> dict[str, Any]:
    return {
        "id": str(payment.id),
        "cart_id": str(payment.cart_id),
        "user_id": str(payment.user_id),
        "payment_method_id": str(payment.payment_method_id),
        "status": payment.status,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "provider_charge_id": payment.provider_charge_id,
        "failure": _failure_to_dict(payment),
        "created_at": _timestamp(payment.created_at),
        "completed_at": _timestamp(payment.completed_at),
    }


def _failure_to_dict(payment: Payment) -> dict[str, str] | None:
    if payment.failure_code is None:
        return None
    return {"code": payment.failure_code, "message": payment.failure_message}


def _timestamp(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
