"""The payment models. See migrations/002_payments.sql for the schema itself."""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import Any, Final

from sqlalchemy import CHAR, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class PaymentStatus:
    """The states a payment can be in.

    A payment starts as PROCESSING and moves once, to SUCCEEDED or to FAILED.
    Nothing moves it back out again: a new attempt is a new payment.
    """

    PROCESSING: Final = "processing"
    SUCCEEDED: Final = "succeeded"
    FAILED: Final = "failed"

    TERMINAL: Final = frozenset({SUCCEEDED, FAILED})


class Payment(db.Model):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    cart_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carts.id")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    payment_method_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_payment_methods.id")
    )
    idempotency_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(CHAR(3))
    provider_charge_id: Mapped[str | None] = mapped_column(Text)
    failure_code: Mapped[str | None] = mapped_column(Text)
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column()

    events: Mapped[list["PaymentEvent"]] = relationship(
        back_populates="payment", order_by="PaymentEvent.created_at"
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in PaymentStatus.TERMINAL

    def record_event(self, to_status: str, **details: Any) -> "PaymentEvent":
        """Move the payment to `to_status` and write the change to its history.

        Keeping the two together is what makes the history trustworthy: there is
        no way to change the status without leaving a trace of why.
        """
        event = PaymentEvent(
            from_status=self.status,
            to_status=to_status,
            details=details,
        )
        self.status = to_status
        if to_status in PaymentStatus.TERMINAL:
            self.completed_at = dt.datetime.now(dt.timezone.utc)
        self.events.append(event)
        return event


class PaymentEvent(db.Model):
    __tablename__ = "payment_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE")
    )
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    payment: Mapped[Payment] = relationship(back_populates="events")
