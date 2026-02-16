CREATE TABLE trades (
    ts          TIMESTAMPTZ      NOT NULL,
    token_id    TEXT             NOT NULL,
    side        TEXT             NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    size        DOUBLE PRECISION NOT NULL,
    trade_id    TEXT
);

SELECT create_hypertable('trades', by_range('ts', INTERVAL '1 day'));

CREATE INDEX idx_trades_token_time ON trades (token_id, ts DESC);

CREATE UNIQUE INDEX idx_trades_trade_id ON trades (trade_id, ts) WHERE trade_id IS NOT NULL;
