-- =============================================================================
-- FX DEEZ v2 AI Trading Team Schema Migration
-- Additive, backwards-compatible with v1
-- =============================================================================

-- Extend ai_decisions with v2 team fields
ALTER TABLE ai_decisions
    ADD COLUMN IF NOT EXISTS engine_version VARCHAR(10) DEFAULT 'v1',
    ADD COLUMN IF NOT EXISTS analyst_opinions JSONB,
    ADD COLUMN IF NOT EXISTS lead_model VARCHAR(100),
    ADD COLUMN IF NOT EXISTS verifier_model VARCHAR(100),
    ADD COLUMN IF NOT EXISTS verifier_verdict VARCHAR(10),
    ADD COLUMN IF NOT EXISTS regime JSONB,
    ADD COLUMN IF NOT EXISTS daily_bias JSONB;

CREATE INDEX IF NOT EXISTS idx_ai_decisions_engine_version ON ai_decisions(engine_version);
CREATE INDEX IF NOT EXISTS idx_ai_decisions_timestamp ON ai_decisions(timestamp);

-- =============================================================================
-- NEW: trade_decision_events (append-only audit trail)
-- =============================================================================
CREATE TABLE IF NOT EXISTS trade_decision_events (
    id SERIAL PRIMARY KEY,
    trade_id INTEGER,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    kind VARCHAR(20) NOT NULL CHECK (kind IN ('ENTRY', 'CHECK', 'CLOSE', 'BIAS')),
    source VARCHAR(20) NOT NULL CHECK (source IN ('AI', 'RULE', 'MANUAL', 'VERIFIER')),
    snapshot JSONB,
    action VARCHAR(20),
    rationale TEXT,
    confidence FLOAT,
    model_used VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_tde_trade_id ON trade_decision_events(trade_id);
CREATE INDEX IF NOT EXISTS idx_tde_ts ON trade_decision_events(ts);

-- =============================================================================
-- NEW: model_performance (per-model tracking for self-improvement)
-- =============================================================================
CREATE TABLE IF NOT EXISTS model_performance (
    id SERIAL PRIMARY KEY,
    model VARCHAR(100) NOT NULL,
    domain VARCHAR(20) NOT NULL CHECK (domain IN ('technical','fundamental','sentiment','macro','lead','verifier','overall')),
    window VARCHAR(20) NOT NULL DEFAULT '30d',
    trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    win_rate FLOAT DEFAULT 0.0,
    expectancy FLOAT DEFAULT 0.0,
    avg_confidence FLOAT DEFAULT 0.0,
    avg_pnl FLOAT DEFAULT 0.0,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (model, domain, window)
);

CREATE INDEX IF NOT EXISTS idx_mp_model ON model_performance(model);
CREATE INDEX IF NOT EXISTS idx_mp_domain ON model_performance(domain);

-- =============================================================================
-- NEW: daily_bias (persisted daily bias per symbol)
-- =============================================================================
CREATE TABLE IF NOT EXISTS daily_bias (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    date DATE NOT NULL,
    bias VARCHAR(10) NOT NULL,
    confidence FLOAT DEFAULT 0.0,
    rationale TEXT,
    key_levels JSONB,
    risk_events JSONB,
    model_used VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_daily_bias_symbol_date ON daily_bias(symbol, date);

-- =============================================================================
-- NEW: historical_candles (local store for Dukascopy data)
-- =============================================================================
CREATE TABLE IF NOT EXISTS historical_candles (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open FLOAT NOT NULL,
    high FLOAT NOT NULL,
    low FLOAT NOT NULL,
    close FLOAT NOT NULL,
    volume INTEGER DEFAULT 0,
    source VARCHAR(20) DEFAULT 'dukascopy'
);

CREATE INDEX IF NOT EXISTS idx_hc_symbol_tf_ts ON historical_candles(symbol, timeframe, timestamp);

-- =============================================================================
-- NEW: optimization_runs (strategy fine-tuning results)
-- =============================================================================
CREATE TABLE IF NOT EXISTS optimization_runs (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    strategy_mode VARCHAR(20) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    params_grid JSONB,
    best_params JSONB,
    fitness FLOAT,
    total_backtests INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_or_symbol ON optimization_runs(symbol);
CREATE INDEX IF NOT EXISTS idx_or_strategy ON optimization_runs(strategy_mode);

-- =============================================================================
-- Add missing indexes on existing tables (performance)
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_trades_status_symbol_close_time ON trades(status, symbol, close_time);
CREATE INDEX IF NOT EXISTS idx_trades_model_used ON trades(model_used) WHERE model_used IS NOT NULL;
