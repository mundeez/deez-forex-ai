-- migrate_round1.sql — v0.9.0
-- Round 1: Data Foundation & Quick Wins
-- Adds columns required for: structured close_reason persistence, MFE/MAE
-- tracking, peak-PnL tracking, session classification, holding-time analytics.
-- Also adds covering indexes for the metric/analytics queries.
--
-- Idempotent — safe to re-run.

-- Trade table additions ------------------------------------------------------
ALTER TABLE trades ADD COLUMN IF NOT EXISTS mfe_pips DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS mae_pips DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS peak_pnl DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS peak_pnl_time TIMESTAMP WITH TIME ZONE;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS session_at_open VARCHAR(20);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS session_at_close VARCHAR(20);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS actual_holding_min DOUBLE PRECISION;

-- Backfill session_at_open/close for existing closed trades ------------------
-- Session UTC ranges: asian 0-7, london 7-16, ny 12-21, overlap = london AND ny.
UPDATE trades
SET session_at_open = CASE
    WHEN EXTRACT(HOUR FROM open_time AT TIME ZONE 'UTC') BETWEEN 12 AND 15 THEN 'london_ny_overlap'
    WHEN EXTRACT(HOUR FROM open_time AT TIME ZONE 'UTC') BETWEEN 7 AND 11 THEN 'london'
    WHEN EXTRACT(HOUR FROM open_time AT TIME ZONE 'UTC') BETWEEN 16 AND 20 THEN 'ny'
    WHEN EXTRACT(HOUR FROM open_time AT TIME ZONE 'UTC') BETWEEN 0 AND 6 THEN 'asian'
    ELSE 'sydney'
END
WHERE session_at_open IS NULL AND open_time IS NOT NULL;

UPDATE trades
SET session_at_close = CASE
    WHEN EXTRACT(HOUR FROM close_time AT TIME ZONE 'UTC') BETWEEN 12 AND 15 THEN 'london_ny_overlap'
    WHEN EXTRACT(HOUR FROM close_time AT TIME ZONE 'UTC') BETWEEN 7 AND 11 THEN 'london'
    WHEN EXTRACT(HOUR FROM close_time AT TIME ZONE 'UTC') BETWEEN 16 AND 20 THEN 'ny'
    WHEN EXTRACT(HOUR FROM close_time AT TIME ZONE 'UTC') BETWEEN 0 AND 6 THEN 'asian'
    ELSE 'sydney'
END
WHERE session_at_close IS NULL AND close_time IS NOT NULL;

-- Backfill actual_holding_min for existing closed trades --------------------
UPDATE trades
SET actual_holding_min = EXTRACT(EPOCH FROM (close_time - open_time)) / 60.0
WHERE actual_holding_min IS NULL
  AND close_time IS NOT NULL
  AND open_time IS NOT NULL;

-- Indexes for analytics + filtering -----------------------------------------
CREATE INDEX IF NOT EXISTS ix_trades_status_close_time
    ON trades (status, close_time DESC);

CREATE INDEX IF NOT EXISTS ix_trades_symbol
    ON trades (symbol);

CREATE INDEX IF NOT EXISTS ix_trades_session_at_open
    ON trades (session_at_open);

CREATE INDEX IF NOT EXISTS ix_ai_decisions_timestamp
    ON ai_decisions (timestamp DESC);

CREATE INDEX IF NOT EXISTS ix_ai_decisions_symbol_timestamp
    ON ai_decisions (symbol, timestamp DESC);

-- Done.
