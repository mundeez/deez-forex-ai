-- Add missing columns for Phase 3 features
ALTER TABLE trades ADD COLUMN IF NOT EXISTS original_position_size DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS trailing_stop_active BOOLEAN DEFAULT FALSE;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS trailing_stop_distance DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS highest_price_seen DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS lowest_price_seen DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS close_reason VARCHAR(30);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS partial_tp_hit BOOLEAN DEFAULT FALSE;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS partial_profit_pnl DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS max_risk_amount DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS partial_pnl DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS closed_portion DOUBLE PRECISION;

-- Check settings table columns
DO $$
BEGIN
    BEGIN
        ALTER TABLE settings ADD COLUMN trailing_stop_enabled BOOLEAN DEFAULT TRUE;
    EXCEPTION WHEN duplicate_column THEN
        RAISE NOTICE 'Column trailing_stop_enabled already exists';
    END;

    BEGIN
        ALTER TABLE settings ADD COLUMN trailing_stop_distance_atr DOUBLE PRECISION DEFAULT 1.0;
    EXCEPTION WHEN duplicate_column THEN
        RAISE NOTICE 'Column trailing_stop_distance_atr already exists';
    END;

    BEGIN
        ALTER TABLE settings ADD COLUMN partial_profit_enabled BOOLEAN DEFAULT TRUE;
    EXCEPTION WHEN duplicate_column THEN
        RAISE NOTICE 'Column partial_profit_enabled already exists';
    END;

    BEGIN
        ALTER TABLE settings ADD COLUMN partial_profit_pct DOUBLE PRECISION DEFAULT 50.0;
    EXCEPTION WHEN duplicate_column THEN
        RAISE NOTICE 'Column partial_profit_pct already exists';
    END;

    BEGIN
        ALTER TABLE settings ADD COLUMN spread_filter_enabled BOOLEAN DEFAULT TRUE;
    EXCEPTION WHEN duplicate_column THEN
        RAISE NOTICE 'Column spread_filter_enabled already exists';
    END;

    BEGIN
        ALTER TABLE settings ADD COLUMN max_spread_to_atr_ratio DOUBLE PRECISION DEFAULT 0.30;
    EXCEPTION WHEN duplicate_column THEN
        RAISE NOTICE 'Column max_spread_to_atr_ratio already exists';
    END;

    BEGIN
        ALTER TABLE settings ADD COLUMN drawdown_guard_enabled BOOLEAN DEFAULT TRUE;
    EXCEPTION WHEN duplicate_column THEN
        RAISE NOTICE 'Column drawdown_guard_enabled already exists';
    END;

    BEGIN
        ALTER TABLE settings ADD COLUMN correlation_guard_enabled BOOLEAN DEFAULT TRUE;
    EXCEPTION WHEN duplicate_column THEN
        RAISE NOTICE 'Column correlation_guard_enabled already exists';
    END;
END $$;
