"""A stand-in for the real payment provider.

It decides the outcome from the card token, so a test — or a person poking at
the API by hand — can ask for a decline as easily as for a success:

    tok_...              charges the card
    tok_..._decline      the bank says no
    tok_..._no_funds     the bank says no, for lack of money
    tok_..._unavailable  the provider cannot be reached at all
    tok_..._flaky        the first call is lost, a retry gets through

It is idempotent on the idempotency key, like a real provider: a second call
with a key it has already seen replays the first answer instead of charging
again. That is what makes retrying a lost request safe.
"""

from __future__ import annotations

import threading
import uuid

from app.providers.base import ChargeRequest, ChargeResult, ProviderUnavailableError

_DECLINE_MARKER = "_decline"
_NO_FUNDS_MARKER = "_no_funds"
_UNAVAILABLE_MARKER = "_unavailable"
_FLAKY_MARKER = "_flaky"


class MockPaymentProvider:
    def __init__(self) -> None:
        # Keyed by idempotency key. A real provider keeps this in its own
        # database; here it lives for as long as the process does.
        self._answers: dict[str, ChargeResult] = {}
        self._keys_seen: set[str] = set()
        self._lock = threading.Lock()
        # Every request that reached the provider, in order. A test asserts on
        # this to show that the card was offered to the bank exactly once.
        self.calls: list[ChargeRequest] = []

    def charge(self, request: ChargeRequest) -> ChargeResult:
        with self._lock:
            self.calls.append(request)
            remembered = self._answers.get(request.idempotency_key)
            if remembered is not None:
                return remembered

            first_call = request.idempotency_key not in self._keys_seen
            self._keys_seen.add(request.idempotency_key)

            token = request.provider_token
            if _UNAVAILABLE_MARKER in token or (_FLAKY_MARKER in token and first_call):
                raise ProviderUnavailableError(
                    f"could not reach the payment provider for {token}"
                )

            answer = self._decide(token)
            self._answers[request.idempotency_key] = answer
            return answer

    @staticmethod
    def _decide(token: str) -> ChargeResult:
        if _DECLINE_MARKER in token:
            return ChargeResult.decline("card_declined", "The card was declined.")
        if _NO_FUNDS_MARKER in token:
            return ChargeResult.decline(
                "insufficient_funds", "The card has insufficient funds."
            )
        return ChargeResult.success(f"ch_mock_{uuid.uuid4().hex}")
