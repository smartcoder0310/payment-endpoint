"""Two requests at once must not charge a card twice.

This is the case the design is really for: a user double-clicking Pay, or a
client retrying while the first request is still running. It is tested with real
threads against a real database, because what stops it is a row lock and a
partial unique index, neither of which exists in a mocked-out test.
"""

from __future__ import annotations

import threading
import uuid

from sqlalchemy import select

from app.models import Payment, PaymentStatus
from tests.conftest import reload
from tests.factories import make_shopper


def _pay_from_thread(app, cart_id, user_id, idempotency_key, results, barrier):
    client = app.test_client()
    barrier.wait(timeout=10)  # let go of both requests at the same moment
    results.append(
        client.post(
            f"/api/v1/carts/{cart_id}/payments",
            headers={"X-User-Id": user_id, "Idempotency-Key": idempotency_key},
            json={},
        )
    )


def _pay_twice_at_once(app, cart, user, *, same_key: bool):
    """Send two payment requests for one cart from two threads at once.

    The ids are read here rather than in the threads: they belong to the main
    thread's session, and a thread has no application context to load them with.
    """
    cart_id, user_id = str(cart.id), str(user.id)
    shared_key = uuid.uuid4().hex
    results: list = []
    barrier = threading.Barrier(2)

    threads = [
        threading.Thread(
            target=_pay_from_thread,
            args=(
                app,
                cart_id,
                user_id,
                shared_key if same_key else uuid.uuid4().hex,
                results,
                barrier,
            ),
        )
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "a request never finished; likely a deadlock"

    return results


def test_two_simultaneous_payments_for_one_cart_charge_it_once(app, session, provider):
    user, cart, product = make_shopper(session, price="45.00", quantity=1, stock=10)

    results = _pay_twice_at_once(app, cart, user, same_key=False)

    # One request paid; the other was told the cart was already being paid for.
    assert sorted(response.status_code for response in results) == [201, 409]
    assert len(provider.calls) == 1
    assert reload(session, product).stock_quantity == 9
    assert reload(session, cart).status == "checked_out"

    payments = session.scalars(select(Payment)).all()
    assert len(payments) == 1
    assert payments[0].status == PaymentStatus.SUCCEEDED


def test_a_double_clicked_retry_is_answered_twice_and_charged_once(
    app, session, provider
):
    """Both requests carry the same key, as a well-behaved client's retry would."""
    user, cart, product = make_shopper(session, stock=10)

    results = _pay_twice_at_once(app, cart, user, same_key=True)

    statuses = sorted(response.status_code for response in results)
    # The loser either sees the winner's payment (201) or is told that a payment
    # for this cart is in flight (409). Both are honest; neither charges twice.
    assert statuses in ([201, 201], [201, 409]), statuses
    assert len(provider.calls) == 1
    assert len(session.scalars(select(Payment)).all()) == 1
    assert reload(session, product).stock_quantity == 9
