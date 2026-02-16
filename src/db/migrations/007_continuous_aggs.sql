-- 1-hour OHLCV candles from price_snapshots
CREATE MATERIALIZED VIEW price_candles_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', ts) AS bucket,
    token_id,
    first(price, ts) AS open,
    max(price) AS high,
    min(price) AS low,
    last(price, ts) AS close,
    avg(volume_24h) AS avg_volume
FROM price_snapshots
GROUP BY bucket, token_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('price_candles_1h',
    start_offset   => INTERVAL '3 hours',
    end_offset     => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);

-- 1-hour trade volume aggregates
CREATE MATERIALIZED VIEW trade_volume_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', ts) AS bucket,
    token_id,
    count(*) AS trade_count,
    sum(size) AS total_size,
    sum(price * size) AS total_value,
    avg(price) AS avg_price
FROM trades
GROUP BY bucket, token_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('trade_volume_1h',
    start_offset   => INTERVAL '3 hours',
    end_offset     => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);
