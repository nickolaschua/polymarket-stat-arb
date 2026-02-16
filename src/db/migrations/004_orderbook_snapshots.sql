CREATE TABLE orderbook_snapshots (
    ts          TIMESTAMPTZ      NOT NULL,
    token_id    TEXT             NOT NULL,
    bids        JSONB,
    asks        JSONB,
    spread      DOUBLE PRECISION,
    midpoint    DOUBLE PRECISION
);

SELECT create_hypertable('orderbook_snapshots', by_range('ts', INTERVAL '7 days'));

CREATE INDEX idx_orderbook_snapshots_token_time ON orderbook_snapshots (token_id, ts DESC);
