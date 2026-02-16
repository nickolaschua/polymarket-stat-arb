CREATE TABLE price_snapshots (
    ts          TIMESTAMPTZ      NOT NULL,
    token_id    TEXT             NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    volume_24h  DOUBLE PRECISION
);

SELECT create_hypertable('price_snapshots', by_range('ts', INTERVAL '1 day'));

CREATE INDEX idx_price_snapshots_token_time ON price_snapshots (token_id, ts DESC);
