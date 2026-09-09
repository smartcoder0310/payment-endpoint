"""What happens when a user pays for a cart."""

from __future__ import annotations

import decimal

from sqlalchemy import select

from app.models import Payment, PaymentStatus
from tests.conftest import reload
from tests.factories import (
    DECLINED_CARD,
    FLAKY_CARD,
    GOOD_CARD,
    UNAVAILABLE_CARD,
    make_payment_method,
    make_shopper,
)


def test_a_paid_cart_is_charged_checked_out_and_taken_off_the_shelf(
    session, provider, pay
):
    user, cart, product = make_shopper(session, price="45.00", quantity=2, stock=10)

    response = pay(cart, user)

    assert response.status_code == 201
    payment = response.get_json()["payment"]
    assert payment["status"] == PaymentStatus.SUCCEEDED
    assert payment["amount"] == "90.00"
    assert payment["currency"] == "USD"
    assert payment["cart_id"] == str(cart.id)
    assert payment["provider_charge_id"].startswith("ch_mock_")
    assert payment["failure"] is None
    assert payment["completed_at"] is not None

    assert reload(session, cart).status == "checked_out"
    assert reload(session, product).stock_quantity == 8

    assert len(provider.calls) == 1
    assert provider.calls[0].amount == decimal.Decimal("90.00")
    assert provider.calls[0].provider_token == GOOD_CARD


def test_the_amount_charged_is_the_price_the_cart_was_filled_at(session, provider, pay):
    user, cart, product = make_shopper(session, price="12.50", quantity=3)

    product.price = decimal.Decimal("99.00")  # the shop puts the price up
    session.commit()

    assert pay(cart, user).get_json()["payment"]["amount"] == "37.50"


def test_a_declined_card_takes_neither_the_money_nor_the_stock(session, pay):
    user, cart, product = make_shopper(
        session, card=DECLINED_CARD, quantity=2, stock=10
    )

    response = pay(cart, user)

    assert response.status_code == 402
    body = response.get_json()
    assert body["error"]["code"] == "card_declined"
    assert body["payment"]["status"] == PaymentStatus.FAILED
    assert body["payment"]["failure"]["code"] == "card_declined"
    assert body["payment"]["provider_charge_id"] is None

    # The cart is left exactly as it was, so the user can try again,
    # and the goods go back on the shelf.
    assert reload(session, cart).status == "active"
    assert reload(session, product).stock_quantity == 10


def test_a_failed_payment_can_be_retried_with_another_card(session, pay):
    user, cart, product = make_shopper(session, card=DECLINED_CARD, stock=10)
    working_card = make_payment_method(
        session, user, provider_token=GOOD_CARD, is_default=False
    )
    session.commit()

    assert pay(cart, user).status_code == 402

    response = pay(cart, user, payment_method_id=str(working_card.id))

    assert response.status_code == 201
    assert reload(session, cart).status == "checked_out"
    assert reload(session, product).stock_quantity == 9
    # The failed attempt is kept alongside the successful one.
    assert len(session.scalars(select(Payment)).all()) == 2


def test_an_unanswered_charge_leaves_the_payment_in_flight(session, pay):
    user, cart, product = make_shopper(session, card=UNAVAILABLE_CARD, stock=10)

    response = pay(cart, user)

    assert response.status_code == 502
    assert response.get_json()["error"]["code"] == "provider_unavailable"

    # We do not know whether the card was charged, so the payment stays open and
    # the stock stays reserved. Deciding either way here would be a guess.
    payment = session.scalars(select(Payment)).one()
    assert payment.status == PaymentStatus.PROCESSING
    assert payment.completed_at is None
    assert reload(session, cart).status == "active"
    assert reload(session, product).stock_quantity == 9


def test_a_payment_in_flight_blocks_a_second_attempt_at_the_same_cart(session, pay):
    user, cart, _ = make_shopper(session, card=UNAVAILABLE_CARD)
    assert pay(cart, user).status_code == 502

    response = pay(cart, user)

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "payment_already_in_progress"


def test_repeating_a_lost_request_with_the_same_key_settles_it(session, provider, pay):
    """The case the idempotency key exists for: an answer lost on the way back.

    The provider is asked again with the same key. Because it is idempotent, the
    card is charged once however many times the client has to ask.
    """
    user, cart, _ = make_shopper(session, card=FLAKY_CARD)

    assert pay(cart, user, idempotency_key="the-same-key").status_code == 502

    response = pay(cart, user, idempotency_key="the-same-key")

    assert response.status_code == 201
    assert response.get_json()["payment"]["status"] == PaymentStatus.SUCCEEDED
    assert len(session.scalars(select(Payment)).all()) == 1
    assert reload(session, cart).status == "checked_out"
    assert len(provider.calls) == 2  # asked twice, charged once


def test_every_step_of_a_payment_is_written_down(session, pay):
    user, cart, _ = make_shopper(session)

    pay(cart, user)

    payment = session.scalars(select(Payment)).one()
    assert [(event.from_status, event.to_status) for event in payment.events] == [
        (None, PaymentStatus.PROCESSING),
        (PaymentStatus.PROCESSING, PaymentStatus.SUCCEEDED),
    ]
    assert payment.events[1].details["provider_charge_id"] == payment.provider_charge_id
