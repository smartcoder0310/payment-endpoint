-- Payments.
--
-- One row per attempt to charge a cart. A user who fails to pay and tries
-- again gets a second row, so the history of attempts is never overwritten.
--
-- Money is NUMERIC, never a float, and the amount and currency are copied onto
-- the row. A payment must stay readable years later, when the cart, the prices
-- and the saved card may all have changed.


CREATE TABLE payments (
    id                 UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_id            UUID           NOT NULL REFERENCES carts(id),
    user_id            UUID           NOT NULL REFERENCES users(id),
    payment_method_id  UUID           NOT NULL REFERENCES user_payment_methods(id),

    -- Supplied by the client so a retried HTTP request charges the card once.
    -- Also handed to the payment provider, which keys its own de-duplication
    -- on it, so a retry after a network failure is safe end to end.
    idempotency_key    TEXT           NOT NULL,

    -- processing — the provider was asked to charge the card, no answer yet.
    -- succeeded   — the money was taken.
    -- failed      — the money was not taken. The user may try again.
    status             TEXT           NOT NULL
                                      CHECK (status IN ('processing', 'succeeded', 'failed')),

    amount             NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    currency           CHAR(3)        NOT NULL,

    -- The provider's own id for the charge. Needed to refund or to reconcile.
    provider_charge_id TEXT,
    failure_code       TEXT,
    failure_message    TEXT,

    created_at         TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    -- Set when the payment reached 'succeeded' or 'failed'.
    completed_at       TIMESTAMPTZ,

    CONSTRAINT chk_payments_completed_at_matches_status CHECK (
        (status = 'processing' AND completed_at IS NULL)
        OR (status <> 'processing' AND completed_at IS NOT NULL)
    ),
    CONSTRAINT chk_payments_failure_reason_only_when_failed CHECK (
        status = 'failed' OR (failure_code IS NULL AND failure_message IS NULL)
    )
);


-- The same request sent twice must not charge the card twice. The key is
-- scoped to the user so one client cannot guess or collide with another's.
CREATE UNIQUE INDEX uq_payments_user_idempotency_key
    ON payments (user_id, idempotency_key);

-- A cart is paid for at most once. At any moment it has at most one payment
-- that is either in flight or successful; failed attempts are free to pile up.
-- The database enforces this, so two concurrent requests cannot both charge:
-- one of them loses the insert.
CREATE UNIQUE INDEX uq_payments_one_live_per_cart
    ON payments (cart_id)
    WHERE status IN ('processing', 'succeeded');

-- Reconciling stuck payments ("which charges have been in flight too long?")
-- and looking up a charge the provider tells us about.
CREATE INDEX idx_payments_processing_created_at
    ON payments (created_at)
    WHERE status = 'processing';

CREATE UNIQUE INDEX uq_payments_provider_charge_id
    ON payments (provider_charge_id)
    WHERE provider_charge_id IS NOT NULL;

CREATE INDEX idx_payments_user_id_created_at ON payments (user_id, created_at DESC);


-- Every status change of a payment, in order. Append only.
-- Money questions are asked after the fact ("why was this card charged?"), and
-- the payments row alone only shows where an attempt ended, not how it got there.
CREATE TABLE payment_events (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_id  UUID        NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
    from_status TEXT,       -- NULL for the event that created the payment.
    to_status   TEXT        NOT NULL,
    -- Whatever we want to be able to read later: the provider's raw answer,
    -- the reason we gave up, the request that caused the change.
    details     JSONB       NOT NULL DEFAULT '{}'::JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_payment_events_payment_id_created_at
    ON payment_events (payment_id, created_at);
