CREATE TABLE resolutions (
    condition_id        TEXT            PRIMARY KEY,
    outcome             TEXT,
    winner_token_id     TEXT,
    resolved_at         TIMESTAMPTZ,
    payout_price        DOUBLE PRECISION,
    detection_method    TEXT,
    created_at          TIMESTAMPTZ     DEFAULT NOW()
);
