# deez-forex-ai

Intelligent 24/7 Forex Trading Platform powered by AI.

## Architecture

- **Frontend:** Next.js 14 + TypeScript + TailwindCSS
- **Backend:** Python FastAPI + SQLAlchemy (async PostgreSQL)
- **Queue/Cache:** Redis + Celery
- **Data Feed:** MetaAPI.cloud or self-hosted MT5 Docker container (ZeroMQ)
- **AI Engine:** OpenRouter.ai (Claude 3.5 Sonnet / GPT-4o)
- **Deployment:** Docker Compose

## Features

- **Multi-Factor Analysis:** Technical (EMA, RSI, MACD, Bollinger, ATR, divergence), Fundamental (economic calendar, interest rate spreads), Sentiment (news, retail, institutional/COT)
- **AI Trade Decisions:** Structured JSON decisions from cloud LLMs via OpenRouter.ai
- **Execution:** Paper trading simulator + live MetaAPI.cloud relay + MT5 container (ZMQ)
- **Risk Management:** Max 2% per trade, daily loss limits, correlation guards
- **Backtesting:** Walk-forward historical replay with Sharpe, profit factor, max drawdown
- **Dashboard:** Real-time market view, AI insights, trade journal

## Quick Start

```bash
# 1. Clone and enter the project
cd deez-forex-ai

# 2. Configure environment variables
cp .env.example .env
# Edit .env and add your API keys:
# - OPENROUTER_API_KEY (required for AI decisions)
# - META_API_TOKEN + META_API_ACCOUNT_ID (required for live trading)
# - NEWS_API_KEY (optional, for news sentiment)
# - FRED_API_KEY (optional, for rate differentials)

# 3. Start the stack
docker-compose up -d --build

# 4. Access the app
# Frontend: http://localhost:23000
# Backend API: http://localhost:28000
# API Docs: http://localhost:28000/docs
```

## Docker Services

| Service | Container Name | Port | Purpose |
|---------|---------------|------|---------|
| PostgreSQL | deez-forex-postgres | 25432 | Trade history, AI decisions |
| Redis | deez-forex-redis | 26379 | Cache, Celery broker |
| FastAPI | deez-forex-backend | 28000 | REST API + WebSocket |
| Celery Worker | deez-forex-celery | - | Background analysis |
| Celery Beat | deez-forex-beat | - | Scheduled tasks |
| Next.js | deez-forex-frontend | 23000 | Trading dashboard |

## API Endpoints

- `GET /health` - Health check
- `GET /api/v1/market/current` - Current EUR/USD price
- `POST /api/v1/ai/analyze` - Trigger full AI analysis + auto-trade
- `GET /api/v1/trades` - List trades
- `GET /api/v1/ai/decisions` - List AI decisions
- `POST /api/v1/trades/manual` - Place manual trade
- `WS /ws` - WebSocket for real-time updates

## 24/7 Operation

Celery Beat runs market analysis every 15 minutes. When a BUY/SELL signal passes risk checks, a paper trade is automatically executed. Switch to live mode by setting `META_API_TOKEN` and changing trade mode.

## Configuration

Edit `.env` to adjust:

- `MAX_RISK_PER_TRADE_PCT` (default: 2.0)
- `MAX_DAILY_LOSS_PCT` (default: 5.0)
- `OPENROUTER_MODEL` (default: anthropic/claude-3.5-sonnet)
- `DEFAULT_PAIR` (default: EURUSD)

## Live Trading Setup

1. Create a MetaAPI.cloud account
2. Deploy the MetaAPI EA on your MT4/MT5 demo/live account
3. Copy your account token and account ID into `.env`
4. Restart the backend: `docker-compose restart backend`
5. Trades will now route to your live account

## Paper Mode vs Live Mode

Without `META_API_TOKEN`, all trades execute in **paper mode** using mock market data. This is perfect for testing and backtesting. Once you provide a MetaAPI token, trades can be sent to your live MT4/MT5 account.

## License

MIT
