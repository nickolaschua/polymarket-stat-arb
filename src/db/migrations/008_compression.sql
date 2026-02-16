-- Enable compression on time-series hypertables
ALTER TABLE price_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'token_id',
    timescaledb.compress_orderby = 'ts DESC'
);

SELECT add_compression_policy('price_snapshots', compress_after => INTERVAL '7 days');

ALTER TABLE orderbook_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'token_id',
    timescaledb.compress_orderby = 'ts DESC'
);

SELECT add_compression_policy('orderbook_snapshots', compress_after => INTERVAL '7 days');

ALTER TABLE trades SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'token_id',
    timescaledb.compress_orderby = 'ts DESC'
);

SELECT add_compression_policy('trades', compress_after => INTERVAL '7 days');

-- Retention policies: drop raw data older than 90 days
-- Continuous aggregates are kept forever
SELECT add_retention_policy('price_snapshots', drop_after => INTERVAL '90 days');
SELECT add_retention_policy('trades', drop_after => INTERVAL '90 days');
