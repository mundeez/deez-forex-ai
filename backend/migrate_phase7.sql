-- Phase 7.1: strategy tournament schema
-- Registered variants, shadow-arm candidates, per-variant stats, measured costs.

CREATE TABLE IF NOT EXISTS strategy_variants (
    id              SERIAL PRIMARY KEY,
    variant_id      VARCHAR(40) UNIQUE NOT NULL,
    family          VARCHAR(30) NOT NULL,
    timeframe       VARCHAR(8)  NOT NULL,
    params          JSONB NOT NULL DEFAULT '{}',
    hypothesis      TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'active',  -- active|retired|promoted
    registered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_at      TIMESTAMPTZ,
    kill_reason     VARCHAR(160)
);

-- Shadow arm: every rule-generated candidate, recorded BEFORE any LLM filter.
-- fk is null while the candidate never reaches the decision pipeline.
CREATE TABLE IF NOT EXISTS strategy_candidates (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    variant_id      VARCHAR(40) NOT NULL,
    symbol          VARCHAR(10) NOT NULL,
    direction       VARCHAR(6)  NOT NULL,           -- BUY|SELL
    entry_price     DOUBLE PRECISION,
    stop_loss       DOUBLE PRECISION,
    take_profit     DOUBLE PRECISION,
    atr             DOUBLE PRECISION,
    timeframe       VARCHAR(8),
    spread_at_signal DOUBLE PRECISION,
    regime          VARCHAR(24),
    llm_verdict     VARCHAR(12),                    -- PASS|VETO|SKIPPED
    ai_decision_id  INTEGER,
    rule_rationale  TEXT
);
CREATE INDEX IF NOT EXISTS ix_strategy_candidates_variant ON strategy_candidates (variant_id, created_at);
CREATE INDEX IF NOT EXISTS ix_strategy_candidates_symbol  ON strategy_candidates (symbol, created_at);

ALTER TABLE ai_decisions ADD COLUMN IF NOT EXISTS variant_id VARCHAR(40);
ALTER TABLE ai_decisions ADD COLUMN IF NOT EXISTS llm_verdict VARCHAR(12);
ALTER TABLE ai_decisions ADD COLUMN IF NOT EXISTS xgb_score DOUBLE PRECISION;
ALTER TABLE ai_decisions ADD COLUMN IF NOT EXISTS pattern_prior_snapshot JSONB;
ALTER TABLE ai_decisions ADD COLUMN IF NOT EXISTS spread_at_decision DOUBLE PRECISION;
ALTER TABLE ai_decisions ADD COLUMN IF NOT EXISTS requested_price DOUBLE PRECISION;

ALTER TABLE trades ADD COLUMN IF NOT EXISTS variant_id VARCHAR(40);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS fill_slippage_pips DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_slippage_pips DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS spread_at_entry DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS spread_at_exit DOUBLE PRECISION;

-- Rolling per-variant statistics snapshot, written by the VariantMonitor task.
CREATE TABLE IF NOT EXISTS variant_stats (
    id              BIGSERIAL PRIMARY KEY,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    variant_id      VARCHAR(40) NOT NULL,
    trades          INTEGER NOT NULL DEFAULT 0,
    wins            INTEGER NOT NULL DEFAULT 0,
    win_rate        DOUBLE PRECISION,
    profit_factor   DOUBLE PRECISION,
    expectancy      DOUBLE PRECISION,           -- mean P&L per trade
    net_pnl         DOUBLE PRECISION,
    max_drawdown    DOUBLE PRECISION,
    t_stat          DOUBLE PRECISION,
    pf_ci90_low     DOUBLE PRECISION,
    xauusd          BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS ix_variant_stats_variant ON variant_stats (variant_id, computed_at);

-- Measured execution costs fed back into the backtest engine.
CREATE TABLE IF NOT EXISTS execution_costs (
    id              BIGSERIAL PRIMARY KEY,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol          VARCHAR(10) NOT NULL,
    session         VARCHAR(20) NOT NULL,       -- asian|london|ny|offhours
    samples         INTEGER NOT NULL DEFAULT 0,
    mean_spread_pips     DOUBLE PRECISION,
    p90_spread_pips      DOUBLE PRECISION,
    mean_entry_slip_pips DOUBLE PRECISION,
    mean_exit_slip_pips  DOUBLE PRECISION,
    p90_exit_slip_pips   DOUBLE PRECISION,
    UNIQUE (symbol, session, computed_at)
);

-- Seed: register the eight pre-registered Phase 7 variants.
INSERT INTO strategy_variants (variant_id, family, timeframe, params, hypothesis) VALUES
('TF-D1-DON20','trend','1d','{"don_entry":20,"don_exit":10,"adx_min":20,"ema":50,"atr_trail":2.0}','Classic Turtle Donchian breakout on D1 — strongest TA evidence (MOP 2012, Hurst 2017)'),
('TF-H4-DON20','trend','4h','{"don_entry":20,"don_exit":10,"adx_min":20,"ema":50,"atr_trail":2.0}','Does the D1 trend edge survive at ~6x frequency? (Menkhoff 2012: decays with horizon)'),
('TF-H1-DON55','trend','1h','{"don_entry":55,"don_exit":20,"adx_min":25,"d1_filter":true,"atr_trail":2.0}','Multi-TF: H1 Donchian(55) gated by D1 trend agreement'),
('SB-M15-LDN','session_breakout','15m','{"range_start":"00:00","range_end":"07:00","window_end":"10:00","min_atr_frac":0.5,"max_atr_frac":1.5,"tp_range_mult":1.0,"hard_exit":"12:00"}','London open breaks the Asian range — best-documented intraday periodicity'),
('SB-H1-NYO','session_breakout','1h','{"range_start":"07:00","range_end":"12:00","window_end":"15:00","min_atr_frac":0.5,"max_atr_frac":1.5,"tp_range_mult":1.0,"hard_exit":"20:00"}','NY open breaks the London range'),
('ND-M15-DRIFT','news_drift','15m','{"delay_min":15,"atr_mult":1.0,"tp_rr":1.5,"time_stop_min":90}','Post-release drift 15 min after high-impact events'),
('MR-H1-BBFADE','mean_reversion','1h','{"bb_len":20,"bb_sd":2.5,"rsi_hi":75,"rsi_lo":25,"adx_max":20,"sl_atr":1.5}','CONTROL/null arm — expected to lose; proves tournament discriminates'),
('LEGACY-M5-EMA','baseline','5m','{}','CONTROL — existing EMA9/21+ADX+RSI rule, known negative edge')
ON CONFLICT (variant_id) DO NOTHING;
