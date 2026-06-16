-- Sprint 1 Migration — 7 new tables for learning system data foundation
-- Run: psql -U postgres -d forex_ai -f backend/migrate_sprint1.sql

-- 1. Economic events with actual vs forecast values
CREATE TABLE IF NOT EXISTS economic_events (
    id          BIGSERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ NOT NULL,
    currency    VARCHAR(3)  NOT NULL,
    event_name  VARCHAR(200) NOT NULL,
    impact      VARCHAR(10),
    actual      FLOAT,
    forecast    FLOAT,
    previous    FLOAT,
    surprise    FLOAT,
    source      VARCHAR(20) DEFAULT 'forexfactory'
);
SELECT create_hypertable('economic_events', 'timestamp', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ix_economic_events_currency_ts ON economic_events(currency, timestamp DESC);

-- 2. COT weekly data (CFTC)
CREATE TABLE IF NOT EXISTS cot_reports (
    id              BIGSERIAL PRIMARY KEY,
    report_date     DATE NOT NULL,
    symbol          VARCHAR(10) NOT NULL,
    nc_long         BIGINT,
    nc_short        BIGINT,
    nc_net          BIGINT,
    nc_net_chg      BIGINT,
    comm_net        BIGINT,
    open_interest   BIGINT,
    spec_pct_oi     FLOAT,
    source          VARCHAR(20) DEFAULT 'cftc'
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_cot_reports_uniq ON cot_reports(report_date, symbol);
CREATE INDEX IF NOT EXISTS ix_cot_reports_symbol ON cot_reports(symbol, report_date DESC);

-- 3. Retail sentiment snapshots
CREATE TABLE IF NOT EXISTS retail_sentiment (
    id          BIGSERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ NOT NULL,
    symbol      VARCHAR(10) NOT NULL,
    long_pct    FLOAT,
    short_pct   FLOAT,
    net_score   FLOAT,
    source      VARCHAR(20) DEFAULT 'myfxbook'
);
SELECT create_hypertable('retail_sentiment', 'timestamp', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ix_retail_sentiment_symbol_ts ON retail_sentiment(symbol, timestamp DESC);

-- 4. Macro timeseries (DXY, VIX, yields, indices)
CREATE TABLE IF NOT EXISTS macro_series (
    id          BIGSERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ NOT NULL,
    series_id   VARCHAR(50) NOT NULL,
    value       FLOAT,
    source      VARCHAR(20)
);
SELECT create_hypertable('macro_series', 'timestamp', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS ix_macro_series_uniq ON macro_series(series_id, timestamp);
CREATE INDEX IF NOT EXISTS ix_macro_series_series_id ON macro_series(series_id, timestamp DESC);

-- 5. Archived news headlines with FinBERT scores
CREATE TABLE IF NOT EXISTS news_headlines (
    id               BIGSERIAL PRIMARY KEY,
    published_at     TIMESTAMPTZ NOT NULL,
    symbol           VARCHAR(10),
    headline         TEXT NOT NULL,
    source           VARCHAR(50),
    finbert_positive FLOAT,
    finbert_negative FLOAT,
    finbert_neutral  FLOAT,
    composite_score  FLOAT,
    processed        BOOLEAN DEFAULT FALSE
);
SELECT create_hypertable('news_headlines', 'published_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ix_news_headlines_symbol ON news_headlines(symbol, published_at DESC);
CREATE INDEX IF NOT EXISTS ix_news_headlines_processed ON news_headlines(processed) WHERE processed = FALSE;

-- 6. Per-trade enriched feature record for ML
CREATE TABLE IF NOT EXISTS trade_patterns (
    id                  BIGSERIAL PRIMARY KEY,
    trade_id            INTEGER REFERENCES trades(id) ON DELETE CASCADE,
    symbol              VARCHAR(10),
    entry_session       VARCHAR(20),
    strategy_mode       VARCHAR(20),
    entry_regime        VARCHAR(20),
    analyst_consensus   FLOAT,
    analyst_combination VARCHAR(50),
    daily_bias_aligned  BOOLEAN,
    verifier_verdict    VARCHAR(10),
    mfe_pips            FLOAT,
    mae_pips            FLOAT,
    mfe_mae_ratio       FLOAT,
    outcome             VARCHAR(10),
    pnl                 FLOAT,
    r_multiple          FLOAT,
    exit_quality_score  FLOAT,
    holding_min         FLOAT,
    optimal_hold_min    FLOAT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_trade_patterns_trade_id ON trade_patterns(trade_id);
CREATE INDEX IF NOT EXISTS ix_trade_patterns_symbol ON trade_patterns(symbol, created_at DESC);

-- 7. Market regime labels per symbol/timeframe
CREATE TABLE IF NOT EXISTS market_regimes (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    symbol          VARCHAR(10) NOT NULL,
    timeframe       VARCHAR(10) NOT NULL,
    regime          VARCHAR(20) NOT NULL,
    adx             FLOAT,
    bb_width_pct    FLOAT,
    atr_pct         FLOAT,
    news_proximity  BOOLEAN DEFAULT FALSE,
    confidence      FLOAT
);
SELECT create_hypertable('market_regimes', 'timestamp', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS ix_market_regimes_uniq ON market_regimes(symbol, timeframe, timestamp);
CREATE INDEX IF NOT EXISTS ix_market_regimes_symbol ON market_regimes(symbol, timeframe, timestamp DESC);
