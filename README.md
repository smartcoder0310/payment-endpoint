# Shop payments

The payment part of an online shop: a SQL schema for payments, and an HTTP
endpoint that pays for a cart with the user's saved card.

Built with Python, Flask, SQLAlchemy and PostgreSQL. The payment provider is
mocked; nothing here talks to a real bank.

---

## Running it

Requires Python 3.11 or later and PostgreSQL 13 or later.

### 1. A database

**With Docker:**

```bash
docker compose up -d
```

That starts PostgreSQL on port 5432 with the user, password and databases the
example configuration expects (`shop` and `shop_test`).

**With a PostgreSQL you already have**, create them yourself:

```sql
CREATE USER shop WITH PASSWORD 'shop';
CREATE DATABASE shop OWNER shop;
CREATE DATABASE shop_test OWNER shop;
```

**With neither**, there is a third way that installs nothing system-wide:

```bash
pip install pgserver
python scripts/local_postgres.py
```

`pgserver` is a Python package that ships PostgreSQL binaries. The script starts
one under `.local-postgres/`, creates both databases, and writes the `.env` for
you — so skip the `cp .env.example .env` below. The server keeps running after
the script exits; run it again after a reboot. It is a local convenience, not
part of the application: see the note at the top of the script.

### 2. The application

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env               # Windows: copy .env.example .env
flask db-upgrade                   # create the tables
flask db-seed                      # optional: the sample shop data from the task
flask run
```

`flask db-upgrade` applies the SQL files in `migrations/` in order and records
what it applied, so it is safe to run again. `flask db-reset` throws the
database away and rebuilds it, for when a test run has left a mess.

### 3. Trying it out

With the seed data loaded, Alice has an active cart holding one Blue Kettle
(45.00) and two Ceramic Mugs (12.50 each):

```bash
curl -i -X POST http://localhost:5000/api/v1/carts/c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1/payments \
  -H 'X-User-Id: 11111111-1111-1111-1111-111111111111' \
  -H 'Idempotency-Key: my-first-payment'
```

```
HTTP/1.1 201 CREATED

{"payment": {"id": "...", "status": "succeeded", "amount": "70.00",
             "currency": "USD", "provider_charge_id": "ch_mock_...", ...}}
```

Send it again with the same `Idempotency-Key` and the same answer comes back,
with no second charge. Send it with a new key and the cart, now checked out,
answers `409 cart_already_paid`.

## Running the tests

The tests need a PostgreSQL database of their own, named by `TEST_DATABASE_URL`
(`.env.example` points it at `shop_test`). **It is dropped and rebuilt on every
run**, so do not point it at anything you want to keep.

```bash
pytest
```

They run against a real PostgreSQL rather than SQLite on purpose: what keeps a
card from being charged twice is a row lock and a partial unique index, and
neither exists in SQLite. A test that swapped the database out would be testing
something other than what runs in production.

---

## The API

### `POST /api/v1/carts/<cart_id>/payments`

Pay for a cart.

| Header | | |
|---|---|---|
| `X-User-Id` | required | who is paying — stands in for real authentication |
| `Idempotency-Key` | required | the client's name for this attempt |

Body (optional):

```json
{"payment_method_id": "11111111-2222-3333-4444-555555555555"}
```

Without it, the user's default saved card is used.

| Status | Meaning |
|---|---|
| `201` | the card was charged |
| `402` | the card was not charged — `error.code` says why (`card_declined`, `insufficient_funds`) |
| `400` | the request was malformed (`invalid_request`) |
| `404` | no such cart, or not this user's cart (`cart_not_found`) |
| `409` | the cart cannot be paid for now (`cart_already_paid`, `payment_already_in_progress`, `cart_not_payable`, `out_of_stock`) |
| `422` | the cart or the card cannot be charged as asked (`cart_empty`, `mixed_currencies`, `payment_method_not_found`, `idempotency_key_reused`) |
| `502` | the provider could not be reached; retry with the same key (`provider_unavailable`) |

Errors all have the same shape:

```json
{"error": {"code": "out_of_stock",
           "message": "Only 2 of 'Wool Blanket' are left.",
           "details": {"product_id": "...", "requested": 3, "available": 2}}}
```

`code` is for programs and is stable; `message` is for people and is not. A
`402` also carries the `payment` itself, because a declined payment is a real
record with an id that the client may want to refer to.

### `GET /api/v1/payments/<payment_id>`

Read a payment back. This is how a client that lost the answer to a `POST` —
or that got a `502` — finds out whether the card was charged.

---

## How it works

### The endpoint

Paying is done in three steps, in two transactions with the call to the payment
provider in between:

1. **Open the payment.** Lock the cart, check that it may be paid for, work out
   the total, take the stock off the shelf, and write a `processing` payment.
   Commit.
2. **Charge the card.** No transaction is held open across this. The provider
   is on the network, and a slow one must not sit on locks that the rest of the
   shop needs.
3. **Record the answer.** Mark the payment `succeeded` or `failed`, and either
   check the cart out or put the stock back.

The point of writing the payment down *before* the charge is that a request
which dies halfway leaves a record of a charge that may have happened, rather
than leaving nothing at all. That record is what step 3 — or a later retry —
comes back to.

### Charging once, and only once

Three things, at three different levels:

- **The idempotency key.** The client names its attempt. A repeat of a finished
  request replays the stored answer without going near the provider. A repeat of
  an *unfinished* one asks the provider again, with the same key, so the
  provider's own de-duplication settles it. Reusing a key for a different cart
  is refused rather than guessed at.
- **A row lock on the cart.** Two requests for one cart are serialised, so the
  second sees the first's payment instead of racing it.
- **A partial unique index.** `payments(cart_id) WHERE status IN
  ('processing', 'succeeded')` — the database itself will not hold two live
  payments for one cart. This is the guarantee; the lock above only makes the
  losing request fail with a clear message instead of a constraint violation.

The test suite drives two real HTTP requests at one cart from two threads and
asserts that the provider was called once.

### Money

`NUMERIC(12, 2)` in the database, `Decimal` in Python, and a **string** in JSON.
JSON numbers are floats in most clients, and `57.50` is not exactly a float; a
cent lost in a payment API turns up on someone's bank statement.

The amount is worked out from `cart_items.unit_price`, the price fixed when the
cart was filled, so a price change between filling and paying cannot surprise
the user. The payment then keeps its own copy of the amount and currency: it has
to stay readable years later, when the cart and the prices have moved on.

### The mock provider

`app/providers/mock.py` decides the outcome from the card token, so any case can
be asked for by hand as easily as in a test:

| Token contains | What happens |
|---|---|
| *(nothing special)* | the card is charged |
| `_decline` | the bank says no |
| `_no_funds` | the bank says no, for lack of money |
| `_unavailable` | the provider cannot be reached at all |
| `_flaky` | the first call is lost; a retry gets through |

It is idempotent on the idempotency key, like a real provider: asked twice with
one key, it charges once and answers twice. That is what makes retrying a lost
request safe, and it is the behaviour the retry path is tested against.

### Layout

```
app/
  api/            HTTP: parsing, serialising, routes, the error envelope
  models/         SQLAlchemy models — shop.py was given, payment.py is new
  providers/      the payment provider interface, and the mock
  services/       the payment flow, pricing, and the domain's own errors
migrations/       001 the given base schema, 002 payments
seeds/            the sample data that came with the task
tests/
```

The rules live in `services/`, which knows nothing about HTTP; `api/` translates
between the two and holds no rules of its own. Each domain error carries the
code and status it should be answered with, so there is no second list of
error mappings to keep in step.

---

## Assumptions

Where the task left something open, this is what was decided and why.

**Authentication is a header.** `X-User-Id` stands in for whatever the shop
really uses. Every request is authorised against it: a user can only pay for
their own cart, with their own card, and can only read their own payments.

**The idempotency key is required, not generated.** A key invented here would be
new on every retry, which is exactly the case it exists to prevent. Requiring it
puts the promise where it belongs — with the client that decides what counts as
one attempt.

**One cart, one payment.** A cart is charged at most once. Failed attempts do
not block a retry; a successful one closes the cart for good. Each attempt is
its own row, so the history of a payment is never overwritten.

**Stock is reserved when the payment opens, and released if it fails.** The shop
sells physical things, so the money and the shelf have to agree. Charging first
and finding out afterwards that the last one sold in between costs a refund;
holding the stock from the moment we ask for money costs a row lock. A cart the
shop cannot fill is refused before the card is touched.

**A cart in flight is frozen.** While a payment is `processing`, the cart is not
to be changed. The cart endpoints are not part of this task; they would check
for a live payment the same way `_reject_if_already_being_paid` does.

**A declined card is a `402`, not a `200`.** The caller asked for money to be
taken and it was not. It is reported as an error, with the payment record
attached.

**Currencies are not converted.** A cart whose products are priced in more than
one currency is refused. One charge, one currency.

**The total is calculated here, in `services/cart_pricing.py`.** The task says
the shop already has a service for this; that module stands in for it, and is
the only place that decides an amount.

## What a production version would need next

Deliberately left out, as beyond a payment endpoint:

- **A reconciliation job** for payments left `processing` — the one case this
  design cannot settle by itself, because only the provider knows the answer. It
  would ask the provider about each stale payment and finish it, releasing the
  stock it holds. The index `idx_payments_processing_created_at` exists for that
  query.
- **Refunds**, and the `refunded` status and refunds table that go with them.
  `provider_charge_id` is stored so that a refund has something to refer to.
- **Webhooks** from the provider, for charges that settle asynchronously.
- **Real authentication**, in place of `X-User-Id`.
- **Rate limiting** on the endpoint, since it costs money to call.
