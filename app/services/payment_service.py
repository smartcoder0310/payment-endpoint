"""Starting a payment for a cart.

The shape of the work, and why it is shaped that way:

  1. In one transaction: lock the cart, check that it may be paid for, take the
     stock off the shelf and write a `processing` payment. Commit.
  2. Outside any transaction: ask the provider to charge the card. This talks to
     the network, and a database transaction must never be held open across it --
     a slow provider would hold locks on rows the rest of the shop needs.
  3. In a second transaction: record the answer, and either check the cart out
     or put the stock back.

Between 1 and 3 the payment is written down as `processing`, so a request that
dies in the middle leaves a record of a charge that may have happened, rather
than nothing at all.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    CART_STATUS_CHECKED_OUT,
    Cart,
    CartItem,
    Payment,
    PaymentStatus,
    Product,
    UserPaymentMethod,
)
from app.providers import ChargeRequest, PaymentProvider, ProviderUnavailableError
from app.services.cart_pricing import calculate_cart_total
from app.services.errors import (
    CartAlreadyPaid,
    CartNotFound,
    CartNotPayable,
    IdempotencyKeyReused,
    OutOfStock,
    PaymentAlreadyInProgress,
    PaymentMethodNotFound,
    ProviderUnavailable,
)

_LIVE_STATUSES = (PaymentStatus.PROCESSING, PaymentStatus.SUCCEEDED)


@dataclass(frozen=True)
class PaymentOutcome:
    payment: Payment
    # True when this request started nothing: an earlier request with the same
    # idempotency key had already finished, and this is its answer again.
    replayed: bool


class PaymentService:
    def __init__(self, session: Session, provider: PaymentProvider) -> None:
        self._session = session
        self._provider = provider

    def start_payment(
        self,
        *,
        user_id: uuid.UUID,
        cart_id: uuid.UUID,
        idempotency_key: str,
        payment_method_id: uuid.UUID | None = None,
    ) -> PaymentOutcome:
        try:
            return self._start_payment(
                user_id=user_id,
                cart_id=cart_id,
                idempotency_key=idempotency_key,
                payment_method_id=payment_method_id,
            )
        except Exception:
            # A payment that could not be finished leaves nothing half-written
            # behind it. What was committed stands -- a `processing` payment is
            # meant to outlive the request that opened it -- and everything
            # still pending is dropped.
            self._session.rollback()
            raise

    def _start_payment(
        self,
        *,
        user_id: uuid.UUID,
        cart_id: uuid.UUID,
        idempotency_key: str,
        payment_method_id: uuid.UUID | None,
    ) -> PaymentOutcome:
        payment = self._find_by_idempotency_key(user_id, idempotency_key)

        if payment is not None and payment.cart_id != cart_id:
            raise IdempotencyKeyReused(
                "This Idempotency-Key was already used to pay for another cart. "
                "Use a new key for a new payment.",
                idempotency_key=idempotency_key,
                payment_id=str(payment.id),
            )

        if payment is not None and payment.is_terminal:
            return PaymentOutcome(payment=payment, replayed=True)

        if payment is None:
            payment = self._open_payment(
                user_id=user_id,
                cart_id=cart_id,
                idempotency_key=idempotency_key,
                payment_method_id=payment_method_id,
            )

        # Either a payment we just opened, or one an earlier request opened and
        # never got an answer for. Both are settled the same way: ask again.
        return PaymentOutcome(payment=self._settle(payment), replayed=False)

    def get_payment(
        self, *, user_id: uuid.UUID, payment_id: uuid.UUID
    ) -> Payment | None:
        return self._session.scalars(
            select(Payment).where(Payment.id == payment_id, Payment.user_id == user_id)
        ).first()

    # --- step 1: open the payment ------------------------------------------

    def _open_payment(
        self,
        *,
        user_id: uuid.UUID,
        cart_id: uuid.UUID,
        idempotency_key: str,
        payment_method_id: uuid.UUID | None,
    ) -> Payment:
        cart = self._lock_cart(cart_id)
        if cart is None or cart.user_id != user_id:
            raise CartNotFound("No such cart.", cart_id=str(cart_id))

        # Asked before the cart's own status, because "you have already paid for
        # this" is the more useful of the two answers when both are true.
        self._reject_if_already_being_paid(cart_id)

        if not cart.is_payable:
            raise CartNotPayable(
                f"A cart with status {cart.status!r} cannot be paid for.",
                cart_id=str(cart_id),
                status=cart.status,
            )

        method = self._find_payment_method(user_id, payment_method_id)
        total = calculate_cart_total(cart)
        self._reserve_stock(list(cart.items))

        payment = Payment(
            cart_id=cart_id,
            user_id=user_id,
            payment_method_id=method.id,
            idempotency_key=idempotency_key,
            amount=total.amount,
            currency=total.currency,
        )
        payment.record_event(
            PaymentStatus.PROCESSING,
            reason="payment_started",
            amount=str(total.amount),
            currency=total.currency,
            payment_method_id=str(method.id),
        )
        self._session.add(payment)

        try:
            self._session.commit()
        except IntegrityError:
            # Another request for this cart got there first, in the moment
            # between our check and our insert. The unique index is the real
            # guarantee that a cart is charged once; the check above only buys a
            # clearer error in the ordinary case.
            self._session.rollback()
            self._reject_if_already_being_paid(cart_id)
            raise

        return payment

    def _lock_cart(self, cart_id: uuid.UUID) -> Cart | None:
        """Take the cart's row lock, so two requests cannot open a payment at once.

        Both transactions of a payment lock the cart first and anything else
        after, so they cannot deadlock against each other.
        """
        return self._session.scalars(
            select(Cart).where(Cart.id == cart_id).with_for_update()
        ).first()

    def _reject_if_already_being_paid(self, cart_id: uuid.UUID) -> None:
        live = self._session.scalars(
            select(Payment)
            .where(Payment.cart_id == cart_id, Payment.status.in_(_LIVE_STATUSES))
            .order_by(Payment.created_at)
        ).first()
        if live is None:
            return
        if live.status == PaymentStatus.SUCCEEDED:
            raise CartAlreadyPaid(
                "This cart has already been paid for.",
                cart_id=str(cart_id),
                payment_id=str(live.id),
            )
        raise PaymentAlreadyInProgress(
            "A payment for this cart is already waiting on the provider.",
            cart_id=str(cart_id),
            payment_id=str(live.id),
        )

    def _find_payment_method(
        self, user_id: uuid.UUID, payment_method_id: uuid.UUID | None
    ) -> UserPaymentMethod:
        query = select(UserPaymentMethod).where(UserPaymentMethod.user_id == user_id)
        if payment_method_id is not None:
            query = query.where(UserPaymentMethod.id == payment_method_id)
        else:
            # No card was named, so use the one the user marked as default,
            # falling back to the most recently saved card.
            query = query.order_by(
                UserPaymentMethod.is_default.desc(),
                UserPaymentMethod.created_at.desc(),
            )

        method = self._session.scalars(query).first()
        if method is None:
            raise PaymentMethodNotFound(
                "The user has no such saved payment method.",
                payment_method_id=str(payment_method_id) if payment_method_id else None,
            )
        return method

    # --- stock -------------------------------------------------------------

    def _reserve_stock(self, items: list[CartItem]) -> None:
        """Take the goods off the shelf before charging for them.

        The shop sells physical things, so the money and the stock have to agree.
        Holding the stock from the moment we ask for money is the cheap way to
        keep that true: the alternative is charging first and finding out
        afterwards that the last one sold in between, which costs a refund.
        """
        self._move_stock(self._quantities_by_product(items), sign=-1)

    def _release_stock(self, cart_id: uuid.UUID) -> None:
        """Put the goods back, because the card was not charged after all."""
        items = self._session.scalars(
            select(CartItem).where(CartItem.cart_id == cart_id)
        ).all()
        self._move_stock(self._quantities_by_product(list(items)), sign=+1)

    @staticmethod
    def _quantities_by_product(items: list[CartItem]) -> Counter:
        """How many of each product the cart wants, one number per product.

        A cart may hold the same product on more than one row.
        """
        wanted: Counter = Counter()
        for item in items:
            wanted[item.product_id] += item.quantity
        return wanted

    def _move_stock(self, quantities: Counter, *, sign: int) -> None:
        # Always in the same order, so two carts holding the same two products
        # cannot lock them crosswise and deadlock.
        products = self._session.scalars(
            select(Product)
            .where(Product.id.in_(list(quantities)))
            .order_by(Product.id)
            .with_for_update()
        ).all()

        for product in products:
            wanted = quantities[product.id]
            if sign < 0 and product.stock_quantity < wanted:
                raise OutOfStock(
                    f"Only {product.stock_quantity} of {product.name!r} are left.",
                    product_id=str(product.id),
                    requested=wanted,
                    available=product.stock_quantity,
                )
            product.stock_quantity += sign * wanted

    # --- steps 2 and 3: charge the card, then record the answer -------------

    def _settle(self, payment: Payment) -> Payment:
        method = self._session.get(UserPaymentMethod, payment.payment_method_id)
        request = ChargeRequest(
            # The payment's own id, not the client's key. The client's key is
            # only unique per user -- two shoppers may both call their request
            # "checkout" -- while the provider knows nothing of our users and
            # would treat one as a repeat of the other. The payment id is unique
            # across the shop and stays the same across retries of this payment,
            # which is exactly what the provider needs to de-duplicate on.
            idempotency_key=str(payment.id),
            provider_token=method.provider_token,
            amount=payment.amount,
            currency=payment.currency,
            description=f"Cart {payment.cart_id}",
        )

        try:
            result = self._provider.charge(request)
        except ProviderUnavailableError as error:
            # The payment stays 'processing'. We do not know whether the card was
            # charged, and guessing either way is worse than saying so: repeating
            # the request with the same idempotency key asks the provider again.
            raise ProviderUnavailable(
                "The payment provider could not be reached. "
                "Retry with the same Idempotency-Key.",
                payment_id=str(payment.id),
            ) from error

        cart = self._lock_cart(payment.cart_id)
        payment = self._session.scalars(
            select(Payment).where(Payment.id == payment.id).with_for_update()
        ).one()

        if payment.is_terminal:
            # A concurrent request settled it while we were on the network. It
            # reached the same answer -- the provider is idempotent -- and it has
            # already done the bookkeeping, so there is nothing left to do.
            self._session.commit()
            return payment

        if result.succeeded:
            payment.provider_charge_id = result.charge_id
            payment.record_event(
                PaymentStatus.SUCCEEDED,
                reason="provider_charged_card",
                provider_charge_id=result.charge_id,
            )
            cart.status = CART_STATUS_CHECKED_OUT
        else:
            payment.failure_code = result.failure_code
            payment.failure_message = result.failure_message
            payment.record_event(
                PaymentStatus.FAILED,
                reason="provider_declined_card",
                failure_code=result.failure_code,
                failure_message=result.failure_message,
            )
            self._release_stock(payment.cart_id)

        self._session.commit()
        return payment

    # --- lookups -----------------------------------------------------------

    def _find_by_idempotency_key(
        self, user_id: uuid.UUID, idempotency_key: str
    ) -> Payment | None:
        return self._session.scalars(
            select(Payment).where(
                Payment.user_id == user_id,
                Payment.idempotency_key == idempotency_key,
            )
        ).first()
