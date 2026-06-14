-- =============================================================================
-- M3: TimescaleDB Continuous Aggregates for Bar Generation
-- v0.8.0-m3
-- =============================================================================
-- Run this after M0 (ticks hypertable exists) and M1/M2 (ticks populated).
-- Creates continuous aggregates for 1m/5m/15m/1h/4h/1D/1W bars from ticks.
-- =============================================================================

-- Helper: drop existing caggs if re-running
DO $$
DECLARE
    cagg_name TEXT;
    caggs TEXT[] := ARRAY[
        'bars_1m', 'bars_5m', 'bars_15m', 'bars_1h',
        'bars_4h', 'bars_1d', 'bars_1w'
    ];
BEGIN
    FOREACH cagg_name IN ARRAY caggs LOOP
        BEGIN
            EXECUTE format('DROP MATERIALIZED VIEW IF EXISTS %I CASCADE', cagg_name);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Could not drop %: %', cagg_name, SQLERRM;
        END;
    END LOOP;
END $$;

-- =============================================================================
-- 1m continuous aggregate
-- =============================================================================
CREATE MATERIALIZED VIEW bars_1m
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket('1 minute', timestamp) AS bucket,
    first(bid, timestamp) AS open,
    max(ask) AS high,
    min(bid) AS low,
    last(ask, timestamp) AS close,
    avg(ask - bid) AS avg_spread,
    count(*) AS tick_count
FROM ticks
GROUP BY symbol, bucket
WITH NO DATA;

-- =============================================================================
-- 5m continuous aggregate
-- =============================================================================
CREATE MATERIALIZED VIEW bars_5m
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket('5 minutes', timestamp) AS bucket,
    first(bid, timestamp) AS open,
    max(ask) AS high,
    min(bid) AS low,
    last(ask, timestamp) AS close,
    avg(ask - bid) AS avg_spread,
    count(*) AS tick_count
FROM ticks
GROUP BY symbol, bucket
WITH NO DATA;

-- =============================================================================
-- 15m continuous aggregate
-- =============================================================================
CREATE MATERIALIZED VIEW bars_15m
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket('15 minutes', timestamp) AS bucket,
    first(bid, timestamp) AS open,
    max(ask) AS high,
    min(bid) AS low,
    last(ask, timestamp) AS close,
    avg(ask - bid) AS avg_spread,
    count(*) AS tick_count
FROM ticks
GROUP BY symbol, bucket
WITH NO DATA;

-- =============================================================================
-- 1h continuous aggregate
-- =============================================================================
CREATE MATERIALIZED VIEW bars_1h
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket('1 hour', timestamp) AS bucket,
    first(bid, timestamp) AS open,
    max(ask) AS high,
    min(bid) AS low,
    last(ask, timestamp) AS close,
    avg(ask - bid) AS avg_spread,
    count(*) AS tick_count
FROM ticks
GROUP BY symbol, bucket
WITH NO DATA;

-- =============================================================================
-- 4h continuous aggregate
-- =============================================================================
CREATE MATERIALIZED VIEW bars_4h
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket('4 hours', timestamp) AS bucket,
    first(bid, timestamp) AS open,
    max(ask) AS high,
    min(bid) AS low,
    last(ask, timestamp) AS close,
    avg(ask - bid) AS avg_spread,
    count(*) AS tick_count
FROM ticks
GROUP BY symbol, bucket
WITH NO DATA;

-- =============================================================================
-- 1D continuous aggregate
-- =============================================================================
CREATE MATERIALIZED VIEW bars_1d
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket('1 day', timestamp) AS bucket,
    first(bid, timestamp) AS open,
    max(ask) AS high,
    min(bid) AS low,
    last(ask, timestamp) AS close,
    avg(ask - bid) AS avg_spread,
    count(*) AS tick_count
FROM ticks
GROUP BY symbol, bucket
WITH NO DATA;

-- =============================================================================
-- 1W continuous aggregate
-- =============================================================================
CREATE MATERIALIZED VIEW bars_1w
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket('1 week', timestamp) AS bucket,
    first(bid, timestamp) AS open,
    max(ask) AS high,
    min(bid) AS low,
    last(ask, timestamp) AS close,
    avg(ask - bid) AS avg_spread,
    count(*) AS tick_count
FROM ticks
GROUP BY symbol, bucket
WITH NO DATA;

-- =============================================================================
-- Refresh Policies (real-time aggregation for recent data)
-- =============================================================================

-- 1m: refresh every 1 minute, keep 1 month window
SELECT add_continuous_aggregate_policy('bars_1m',
    start_offset => INTERVAL '1 month',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute'
);

-- 5m: refresh every 5 minutes
SELECT add_continuous_aggregate_policy('bars_5m',
    start_offset => INTERVAL '3 months',
    end_offset => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes'
);

-- 15m: refresh every 15 minutes
SELECT add_continuous_aggregate_policy('bars_15m',
    start_offset => INTERVAL '6 months',
    end_offset => INTERVAL '15 minutes',
    schedule_interval => INTERVAL '15 minutes'
);

-- 1h: refresh every 1 hour
SELECT add_continuous_aggregate_policy('bars_1h',
    start_offset => INTERVAL '1 year',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);

-- 4h: refresh every 4 hours
SELECT add_continuous_aggregate_policy('bars_4h',
    start_offset => INTERVAL '1 year',
    end_offset => INTERVAL '4 hours',
    schedule_interval => INTERVAL '4 hours'
);

-- 1d: refresh daily
SELECT add_continuous_aggregate_policy('bars_1d',
    start_offset => INTERVAL '2 years',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day'
);

-- 1w: refresh weekly
SELECT add_continuous_aggregate_policy('bars_1w',
    start_offset => INTERVAL '5 years',
    end_offset => INTERVAL '1 week',
    schedule_interval => INTERVAL '1 week'
);

-- =============================================================================
-- Retention Policies
-- =============================================================================

-- Drop existing retention policy on ticks if any
DO $$
BEGIN
    PERFORM remove_retention_policy('ticks', if_exists => true);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'No existing retention policy on ticks';
END $$;

-- Retain raw ticks for 90 days (compressed chunks kept longer)
SELECT add_retention_policy('ticks', INTERVAL '90 days');

-- Retain bars_1m for 1 year
SELECT add_retention_policy('bars_1m', INTERVAL '1 year');

-- Retain bars_5m for 2 years
SELECT add_retention_policy('bars_5m', INTERVAL '2 years');

-- Retain bars_15m for 3 years
SELECT add_retention_policy('bars_15m', INTERVAL '3 years');

-- Retain bars_1h for 5 years
SELECT add_retention_policy('bars_1h', INTERVAL '5 years');

-- Retain bars_4h for 10 years
SELECT add_retention_policy('bars_4h', INTERVAL '10 years');

-- Retain bars_1d and bars_1w indefinitely (no retention)
