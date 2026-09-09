"""A cart is charged once, however many times the request arrives."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Payment
from tests.conftest import reload
from tests.factories import DECLINED_CARD, make_cart, make_shopper


def test_the_same_request_sent_twice_charges_the_card_once(session, provider, pay):
    user, cart, product = make_shopper(session, quantity=2, stock=10)

    first = pay(cart, user, idempotency_key="one-attempt")
    second = pay(cart, user, idempotency_key="one-attempt")

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.get_json() == second.get_json()

    assert len(provider.calls) == 1
    assert len(session.scalars(select(Payment)).all()) == 1
    assert reload(session, product).stock_quantity == 8


def test_a_repeated_request_is_answered_the_same_way_when_it_failed(
    session, provider, pay
):
    user, cart, product = make_shopper(session, card=DECLINED_CARD, quantity=2, stock=10)

    first = pay(cart, user, idempotency_key="one-attempt")
    second = pay(cart, user, idempotency_key="one-attempt")

    assert first.status_code == 402
    assert first.get_json() == second.get_json()

    assert len(provider.calls) == 1
    # The stock was put back once, not twice.
    assert reload(session, product).stock_quantity == 10


def test_a_key_cannot_be_reused_for_a_different_cart(session, pay):
    user, cart, product = make_shopper(session)
    another_cart = make_cart(session, user, items=[(product, 1)])
    session.commit()

    assert pay(cart, user, idempotency_key="reused").status_code == 201

    response = pay(another_cart, user, idempotency_key="reused")

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "idempotency_key_reused"
    assert len(session.scalars(select(Payment)).all()) == 1


def test_a_paid_cart_cannot_be_paid_for_again_with_a_new_key(session, provider, pay):
    user, cart, _ = make_shopper(session)
    assert pay(cart, user).status_code == 201

    response = pay(cart, user)

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "cart_already_paid"
    assert len(provider.calls) == 1


def test_two_users_may_choose_the_same_idempotency_key(session, pay):
    """Keys are the client's to pick, so they only have to be unique per user."""
    first_user, first_cart, _ = make_shopper(session)
    second_user, second_cart, _ = make_shopper(session)

    assert pay(first_cart, first_user, idempotency_key="checkout").status_code == 201
    assert pay(second_cart, second_user, idempotency_key="checkout").status_code == 201

    assert len(session.scalars(select(Payment)).all()) == 2
