"""The contract between this service and whoever actually moves the money."""

from __future__ import annotations

import decimal
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChargeRequest:
    """A request to take `amount` off the card behind `provider_token`."""

    idempotency_key: str
    provider_token: str
    amount: decimal.Decimal
    currency: str
    description: str


@dataclass(frozen=True)
class ChargeResult:
    """What the provider answered.

    A decline is an answer, not an error: the provider was reached and said no.
    Only losing the answer entirely is an error, and that raises
    ProviderUnavailableError instead.
    """

    succeeded: bool
    charge_id: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    @classmethod
    def success(cls, charge_id: str) -> "ChargeResult":
        return cls(succeeded=True, charge_id=charge_id)

    @classmethod
    def decline(cls, code: str, message: str) -> "ChargeResult":
        return cls(succeeded=False, failure_code=code, failure_message=message)


class ProviderUnavailableError(Exception):
    """The provider could not be reached, or gave no usable answer.

    The charge may or may not have gone through. The caller must not assume
    either way; it retries with the same idempotency key to find out.
    """


class PaymentProvider(Protocol):
    def charge(self, request: ChargeRequest) -> ChargeResult:
        """Charge the card, or explain why not.

        Must be idempotent on `request.idempotency_key`: calling it twice with
        the same key takes the money once and returns the same answer twice.
        """
