"""The requests the endpoint refuses, and how it says so."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Payment
from tests.conftest import reload
from tests.factories import (
    make_cart,
    make_payment_method,
    make_product,
    make_shopper,
    make_user,
)


def assert_error(response, status, code):
    assert response.status_code == status, response.get_json()
    assert response.get_json()["error"]["code"] == code


# --- the request itself ---------------------------------------------------


def test_the_caller_must_say_who_is_paying(client, session):
    _, cart, _ = make_shopper(session)

    response = client.post(
        f"/api/v1/carts/{cart.id}/payments", headers={"Idempotency-Key": "k"}, json={}
    )

    assert_error(response, 400, "invalid_request")


def test_an_idempotency_key_is_required(client, session):
    user, cart, _ = make_shopper(session)

    response = client.post(
        f"/api/v1/carts/{cart.id}/payments",
        headers={"X-User-Id": str(user.id)},
        json={},
    )

    assert_error(response, 400, "invalid_request")
    assert "Idempotency-Key" in response.get_json()["error"]["message"]


def test_a_body_that_is_not_json_is_refused(client, session):
    user, cart, _ = make_shopper(session)

    response = client.post(
        f"/api/v1/carts/{cart.id}/payments",
        headers={
            "X-User-Id": str(user.id),
            "Idempotency-Key": "k",
            "Content-Type": "application/json",
        },
        data="not json",
    )

    assert_error(response, 400, "invalid_request")


def test_a_payment_method_that_is_not_a_uuid_is_refused(session, pay):
    user, cart, _ = make_shopper(session)

    response = pay(cart, user, payment_method_id="the-blue-one")

    assert_error(response, 400, "invalid_request")


# --- the cart -------------------------------------------------------------


def test_an_unknown_cart_is_not_found(session, pay):
    user, _, _ = make_shopper(session)

    assert_error(pay(uuid.uuid4(), user), 404, "cart_not_found")


def test_a_user_cannot_pay_for_someone_elses_cart(session, pay):
    _, cart, _ = make_shopper(session)
    intruder = make_user(session)
    make_payment_method(session, intruder)
    session.commit()

    response = pay(cart, intruder)

    # Answered as "no such cart", so that a stranger cannot learn which cart ids
    # are real by asking.
    assert_error(response, 404, "cart_not_found")
    assert session.scalars(select(Payment)).all() == []


def test_an_abandoned_cart_cannot_be_paid_for(session, pay):
    user = make_user(session)
    make_payment_method(session, user)
    product = make_product(session)
    cart = make_cart(session, user, items=[(product, 1)], status="abandoned")
    session.commit()

    assert_error(pay(cart, user), 409, "cart_not_payable")


def test_an_empty_cart_cannot_be_paid_for(session, pay):
    user = make_user(session)
    make_payment_method(session, user)
    cart = make_cart(session, user)
    session.commit()

    assert_error(pay(cart, user), 422, "cart_empty")


def test_a_cart_priced_in_two_currencies_cannot_be_paid_for(session, pay):
    user = make_user(session)
    make_payment_method(session, user)
    in_dollars = make_product(session, price="10.00", currency="USD")
    in_euros = make_product(session, price="10.00", currency="EUR")
    cart = make_cart(session, user, items=[(in_dollars, 1), (in_euros, 1)])
    session.commit()

    assert_error(pay(cart, user), 422, "mixed_currencies")


# --- the card -------------------------------------------------------------


def test_a_user_with_no_saved_card_cannot_pay(session, pay):
    user = make_user(session)
    product = make_product(session)
    cart = make_cart(session, user, items=[(product, 1)])
    session.commit()

    assert_error(pay(cart, user), 422, "payment_method_not_found")


def test_a_card_belonging_to_another_user_cannot_be_charged(session, pay):
    user, cart, _ = make_shopper(session)
    stranger = make_user(session)
    stranger_card = make_payment_method(session, stranger)
    session.commit()

    response = pay(cart, user, payment_method_id=str(stranger_card.id))

    assert_error(response, 422, "payment_method_not_found")


# --- the shelf ------------------------------------------------------------


def test_a_cart_the_shop_cannot_fill_is_not_charged(session, provider, pay):
    user, cart, product = make_shopper(session, quantity=3, stock=2)

    response = pay(cart, user)

    assert_error(response, 409, "out_of_stock")
    assert response.get_json()["error"]["details"]["available"] == 2
    # Nothing was attempted: no charge, no payment, no change to the shelf.
    assert provider.calls == []
    assert session.scalars(select(Payment)).all() == []
    assert reload(session, product).stock_quantity == 2
    assert reload(session, cart).status == "active"
