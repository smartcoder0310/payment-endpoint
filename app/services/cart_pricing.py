"""What a cart costs.

The task says the shop already has a service that works out the total, so this
module stands in for it. It is the one place that decides the amount, and the
payment code asks it rather than adding up prices itself.
"""

from __future__ import annotations

import decimal
from dataclasses import dataclass

from app.models import Cart
from app.services.errors import CartEmpty, MixedCurrencies

_CENTS = decimal.Decimal("0.01")


@dataclass(frozen=True)
class CartTotal:
    amount: decimal.Decimal
    currency: str


def calculate_cart_total(cart: Cart) -> CartTotal:
    """Add up the cart at the prices that were fixed when it was filled.

    Uses cart_items.unit_price, not the product's price today, so a price change
    between filling the cart and paying for it cannot surprise the user.
    """
    if not cart.items:
        raise CartEmpty("The cart has no items to pay for.", cart_id=str(cart.id))

    currencies = {item.product.currency for item in cart.items}
    if len(currencies) > 1:
        raise MixedCurrencies(
            "The cart holds products priced in more than one currency.",
            cart_id=str(cart.id),
            currencies=sorted(currencies),
        )

    amount = sum(
        (item.unit_price * item.quantity for item in cart.items),
        start=decimal.Decimal("0"),
    )
    return CartTotal(
        amount=amount.quantize(_CENTS, rounding=decimal.ROUND_HALF_UP),
        currency=currencies.pop(),
    )
