-- Sprint 8: Historical Data Ingestion & System Training
-- Run: psql -U forex -d deez_forex -f migrate_sprint8.sql

-- Add unique constraints for idempotent ingestion
CREATE UNIQUE INDEX IF NOT EXISTS ix_historical_candles_unique
    ON historical_candles (symbol, timeframe, timestamp);

CREATE UNIQUE INDEX IF NOT EXISTS ix_macro_series_unique
    ON macro_series (series_id, timestamp);

-- Verify data ingestion (expected counts after training run)
-- historical_candles: ~45,000 rows (9 pairs x 5,000 1h candles)
-- macro_series: ~1,934 rows (FRED + yfinance, 6 months)
