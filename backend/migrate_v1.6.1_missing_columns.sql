-- Migration: Add missing columns from Sprints 2-7 that were in models but not DB
-- Fixes 500 errors on /api/v1/ai/decisions and related endpoints

-- ai_decisions: missing qdrant_point_id (Sprint 3)
ALTER TABLE ai_decisions ADD COLUMN IF NOT EXISTS qdrant_point_id VARCHAR(50);

-- trades: missing columns from Sprint 2-3
ALTER TABLE trades ADD COLUMN IF NOT EXISTS unrealized_pnl DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_quality_score DOUBLE PRECISION;

-- backtest_runs: missing columns from Sprint 5
ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS backtest_type VARCHAR(20) DEFAULT 'walk_forward';
ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS regime VARCHAR(20);
ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS mc_ruin_probability DOUBLE PRECISION;
ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS mc_median_dd_pct DOUBLE PRECISION;
