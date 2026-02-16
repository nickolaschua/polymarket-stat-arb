CREATE TABLE markets (
    condition_id    TEXT            PRIMARY KEY,
    question        TEXT            NOT NULL,
    slug            TEXT,
    market_type     TEXT,
    outcomes        TEXT[],
    clob_token_ids  TEXT[],
    active          BOOLEAN         DEFAULT true,
    closed          BOOLEAN         DEFAULT false,
    end_date_iso    TEXT,
    created_at      TIMESTAMPTZ     DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_markets_active ON markets (active) WHERE active = true;
