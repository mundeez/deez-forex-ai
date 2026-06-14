-- ============================================================================
-- Migration: v0.8.0 M0 — TimescaleDB Extension + Tick Pipeline Schema
-- Run this against an EXISTING database to upgrade from v0.7.x to v0.8.0-m0
-- New deployments get this automatically via init.sql on first startup.
-- ============================================================================

-- 1. Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 2. Raw tick store
CREATE TABLE IF NOT EXISTS ticks (
    symbol      VARCHAR(10)  NOT NULL,
    timestamp   TIMESTAMPTZ  NOT NULL,
    bid         DOUBLE PRECISION NOT NULL,
    ask         DOUBLE PRECISION NOT NULL,
    bid_vol     REAL,
    ask_vol     REAL,
    spread_pips DOUBLE PRECISION GENERATED ALWAYS AS (
        (ask - bid) * CASE symbol
            WHEN 'USDJPY' THEN 100.0
            WHEN 'GBPJPY' THEN 100.0
            WHEN 'XAUUSD' THEN 10.0
            WHEN 'US30'   THEN 1.0
            WHEN 'NAS100' THEN 1.0
            WHEN 'SPX500' THEN 1.0
            ELSE 10000.0
        END
    ) STORED,
    source      VARCHAR(20)  DEFAULT 'dukascopy',
    created_at  TIMESTAMPTZ  DEFAULT NOW(),
    PRIMARY KEY (symbol, timestamp)
);

-- Convert to hypertable (safe if already exists)
SELECT create_hypertable('ticks', 'timestamp', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_ticks_symbol_timestamp ON ticks (symbol, timestamp DESC);

-- 3. Ingestion state / checkpoint table
CREATE TABLE IF NOT EXISTS ingestion_state (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(10)  NOT NULL,
    source          VARCHAR(20)  NOT NULL DEFAULT 'dukascopy',
    last_ingested_at TIMESTAMPTZ,
    last_ingested_hour TIMESTAMPTZ,
    status          VARCHAR(20)  NOT NULL DEFAULT 'idle',
    total_ticks     BIGINT       DEFAULT 0,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE(symbol, source)
);

-- 4. Bars hypertable (future replacement for market_data)
CREATE TABLE IF NOT EXISTS bars (
    symbol      VARCHAR(10)  NOT NULL,
    timeframe   VARCHAR(10)  NOT NULL,
    timestamp   TIMESTAMPTZ  NOT NULL,
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      BIGINT       DEFAULT 0,
    avg_spread  DOUBLE PRECISION,
    source      VARCHAR(20)  DEFAULT 'dukascopy',
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

SELECT create_hypertable('bars', 'timestamp', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_bars_symbol_tf_ts ON bars (symbol, timeframe, timestamp DESC);

-- 5. Compression policy on ticks (chunks older than 7 days)
SELECT add_compression_policy('ticks', INTERVAL '7 days', if_not_exists => TRUE);
