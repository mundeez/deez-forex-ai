# Deez Forex AI v0.7.0 — AI Resilience & Auto-Trade Recovery

**Release Date:** 2026-05-21  
**Previous Version:** v0.6.2

---

## Summary

v0.7.0 is a critical resilience release that fixes the silent auto-trade failure caused by exhausted OpenRouter API credits. The system now gracefully handles AI service outages with configurable fallback strategies, provides real-time operational visibility via a health API and audit logging, and lets you switch between 7 AI models at runtime — including zero-cost free models for testing.

## What Was Broken

The app was left on auto-trade for an entire day with **zero trades executed**. Root cause investigation found:

1. **OpenRouter API returned 402 Payment Required** — the `claude-sonnet-4.5` model credits were exhausted
2. **The error was unhandled** — the entire `run_full_analysis` Celery task crashed on every cycle (every 5 minutes)
3. **Zero user visibility** — errors only appeared in Docker logs, no notification, no dashboard indicator
4. **No fallback** — when AI was down, the system simply stopped working

## What's Fixed

| Issue | Fix |
|---|---|
| AI API errors crash the pipeline | try/except wraps all AI calls; fallback generates decisions |
| No visibility into failures | `GET /api/v1/system/health` + audit logging + notifications |
| Can't switch models without restart | DB-backed `ai_model` setting with frontend dropdown |
| Free models return lower confidence | Confidence threshold lowered to 0.40, aggressiveness to "aggressive" |
| News date parsing fails on ISO 8601 | Added `datetime.fromisoformat()` fallback |

## New Features

### AI Model Selector
Choose from 7 models in **Settings → AI**. Hover for descriptions:
- **NVIDIA Nemotron 120B (Free)** — current default, zero cost
- **DeepSeek V4 Flash (Free)** — excellent numerical reasoning
- **Gemma 4 26B (Free)** — Google's latest open model
- **Gemini 2.5 Flash** — best JSON mode (~$0.15/M)
- **DeepSeek V3** — nearly free (~$0.0001/decision)
- **GPT-4o Mini** — reliable JSON (~$0.15/M)
- **Claude Sonnet 4.5** — previous default (expensive)

### AI Fallback Strategy
When AI is unavailable, choose:
- **Rule-Based Technical** — EMA crossover + ADX + RSI generate signals
- **Pause & Alert** — stop trading, notify user
- **Hold All** — safe default, no trades

### System Health API
```bash
curl http://localhost:28000/api/v1/system/health
```
Returns: AI availability, last analysis timestamp, current model, open positions, auto-trading status.

### Audit Logging
Every trade decision is traced through the full pipeline:
```
[AUDIT] GBPUSD: AI=BUY(0.62) → Risk=OK → SL/TP=OK → EXECUTED(0.03 lots)
[AUDIT] EURUSD: AI=HOLD(0.30) — no trade signal
[AUDIT] GBPJPY: AI=BUY(0.48) → BLOCKED: confidence 0.48 < 0.40 threshold
```

## Tuning for Free Models

Default settings have been adjusted for free-model operation:

| Setting | Old | New |
|---|---|---|
| AI Confidence Threshold | 0.60 | 0.40 |
| Fallback Strategy | hold | rule_based |
| Trade Aggressiveness | moderate | aggressive |
| AI Model | claude-sonnet-4.5 | nemotron-120b (free) |

## Recommended Next Steps

1. **Monitor audit logs**: `docker logs -f deez-forex-celery | grep AUDIT`
2. **Check health**: `curl localhost:28000/api/v1/system/health`
3. **Fund OpenRouter** ($5 minimum) for better models — switch to `deepseek/deepseek-chat` or `google/gemini-2.5-flash` in the dropdown
4. **Adjust thresholds** as you observe the free model's behavior

## Files Changed

```
backend/app/config.py
backend/app/tasks/analysis_tasks.py
backend/app/ai/openrouter_client.py
backend/app/services/settings_service.py
backend/app/schemas.py
backend/app/main.py
backend/app/services/news_service.py
backend/app/services/notification_service.py
frontend/src/app/settings/page.tsx
CHANGELOG.md (new)
RELEASE_NOTES_v0.7.0.md (new)
```

## Testing

All 49 backend tests pass:
```
============================== 49 passed in 3.10s ==============================
```

---

Generated with [Devin](https://cli.devin.ai/docs)