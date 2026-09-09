"""Builders for the shop rows a payment test needs.

Everything has a sensible default, so a test writes down only what it is about:
a test about stock says how much stock there is and nothing else.
"""

from __future__ import annotations

import decimal
import itertools
import uuid

from app.models import Cart, CartItem, Product, User, UserPaymentMethod

_counter = itertools.count(1)

# The mock provider reads the outcome of a charge off the token. See app/providers/mock.py.
GOOD_CARD = "tok_test_visa"
DECLINED_CARD = "tok_test_decline"
UNAVAILABLE_CARD = "tok_test_unavailable"
FLAKY_CARD = "tok_test_flaky"


def make_user(session, **overrides) -> User:
    number = next(_counter)
    user = User(
        id=uuid.uuid4(),
        email=overrides.pop("email", f"user{number}@example.com"),
        name=overrides.pop("name", f"User {number}"),
        **overrides,
    )
    session.add(user)
    session.flush()
    return user


def make_product(session, *, price="10.00", stock_quantity=100, currency="USD", **overrides) -> Product:
    product = Product(
        id=uuid.uuid4(),
        name=overrides.pop("name", f"Product {next(_counter)}"),
        price=decimal.Decimal(price),
        currency=currency,
        stock_quantity=stock_quantity,
        **overrides,
    )
    session.add(product)
    session.flush()
    return product


def make_payment_method(session, user, *, provider_token=GOOD_CARD, **overrides) -> UserPaymentMethod:
    method = UserPaymentMethod(
        id=uuid.uuid4(),
        user_id=user.id,
        provider_token=provider_token,
        last_four=overrides.pop("last_four", "4242"),
        is_default=overrides.pop("is_default", True),
        **overrides,
    )
    session.add(method)
    session.flush()
    return method


def make_cart(session, user, *, items=(), status="active") -> Cart:
    """A cart, optionally filled: items is a sequence of (product, quantity).

    Each item is priced at the product's price of the moment, which is what the
    cart service does when a user puts something in the basket.
    """
    cart = Cart(id=uuid.uuid4(), user_id=user.id, status=status)
    session.add(cart)
    session.flush()

    for product, quantity in items:
        session.add(
            CartItem(
                id=uuid.uuid4(),
                cart_id=cart.id,
                product_id=product.id,
                quantity=quantity,
                unit_price=product.price,
            )
        )
    session.flush()
    return cart


def make_shopper(session, *, card=GOOD_CARD, price="45.00", quantity=1, stock=10):
    """A user with a saved card and one active cart with something in it.

    The starting point of nearly every test here.
    """
    user = make_user(session)
    make_payment_method(session, user, provider_token=card)
    product = make_product(session, price=price, stock_quantity=stock)
    cart = make_cart(session, user, items=[(product, quantity)])
    session.commit()
    return user, cart, product
