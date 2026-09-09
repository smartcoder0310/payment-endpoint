"""Models for the tables that already existed before the payment part.

They are mapped read-only from this service's point of view, except for the two
columns a payment must change: the status of a cart it paid for, and the stock
it takes off the shelf.

The base schema defaults `updated_at` on insert but has no trigger to maintain
it afterwards, so the mapping keeps it current when a row here is changed.

The constraints in the tables are not repeated here. migrations/ is the one
description of the schema; these classes only say how to read and write it.
"""

from __future__ import annotations

import datetime as dt
import decimal
import uuid

from sqlalchemy import CHAR, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

CartStatus = str
CART_STATUS_ACTIVE: CartStatus = "active"
CART_STATUS_CHECKED_OUT: CartStatus = "checked_out"
CART_STATUS_ABANDONED: CartStatus = "abandoned"


class User(db.Model):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


class Product(db.Model):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    price: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(CHAR(3), default="USD")
    stock_quantity: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


class Cart(db.Model):
    __tablename__ = "carts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    status: Mapped[CartStatus] = mapped_column(Text, default=CART_STATUS_ACTIVE)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart", order_by="CartItem.created_at"
    )

    @property
    def is_payable(self) -> bool:
        return self.status == CART_STATUS_ACTIVE


class CartItem(db.Model):
    __tablename__ = "cart_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    cart_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id")
    )
    quantity: Mapped[int] = mapped_column()
    unit_price: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    cart: Mapped[Cart] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class UserPaymentMethod(db.Model):
    __tablename__ = "user_payment_methods"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    provider_token: Mapped[str] = mapped_column(Text)
    last_four: Mapped[str | None] = mapped_column(CHAR(4))
    is_default: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
