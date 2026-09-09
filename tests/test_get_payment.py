"""Reading a payment back."""

from __future__ import annotations

import uuid

from app.models import PaymentStatus
from tests.factories import UNAVAILABLE_CARD, make_shopper, make_user


def test_a_payment_can_be_read_back(client, session, pay):
    user, cart, _ = make_shopper(session)
    created = pay(cart, user).get_json()["payment"]

    response = client.get(
        f"/api/v1/payments/{created['id']}", headers={"X-User-Id": str(user.id)}
    )

    assert response.status_code == 200
    assert response.get_json()["payment"] == created


def test_a_payment_left_in_flight_reports_itself_as_such(client, session, pay):
    """How a client that lost the answer finds out where its payment stands."""
    user, cart, _ = make_shopper(session, card=UNAVAILABLE_CARD)
    # The 502 does not carry the payment itself, but it does say which payment
    # was left open, which is what makes it possible to go and look.
    lost = pay(cart, user)
    payment_id = lost.get_json()["error"]["details"]["payment_id"]

    response = client.get(
        f"/api/v1/payments/{payment_id}", headers={"X-User-Id": str(user.id)}
    )

    assert response.status_code == 200
    assert response.get_json()["payment"]["status"] == PaymentStatus.PROCESSING


def test_a_payment_belongs_to_the_user_who_made_it(client, session, pay):
    user, cart, _ = make_shopper(session)
    payment_id = pay(cart, user).get_json()["payment"]["id"]
    stranger = make_user(session)
    session.commit()

    response = client.get(
        f"/api/v1/payments/{payment_id}", headers={"X-User-Id": str(stranger.id)}
    )

    assert response.status_code == 404


def test_an_unknown_payment_is_not_found(client, session):
    user = make_user(session)
    session.commit()

    response = client.get(
        f"/api/v1/payments/{uuid.uuid4()}", headers={"X-User-Id": str(user.id)}
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "payment_not_found"
