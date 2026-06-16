# Deez Forex AI — Trading Team Reference

**Version:** v0.8.0  
**Architecture:** Multi-Tier v2 AI Decision Engine  
**Last Updated:** 2026-06-16

---

## Overview

The v2 engine uses a **6-tier multi-agent pipeline**. Domain-specific analysts (technical, fundamental, sentiment, macro) feed a Lead Strategist, which is then reviewed by a Verifier. Each agent can use a different OpenRouter model, enabling latency-aware assignments — fast models for the hot path, reasoning models for deep analysis and verification.

> **How it works:** The frontend lets you select a **Model Suite** (Free, Production, Extreme, or Custom). This suite determines which specific OpenRouter model each team member uses. When you change the suite in Settings, every AI decision from that point forward uses the new model assignments.

---

## Decision Flow

```
Daily Bias (cached, cheap lookup)
        |
        v
Technical Analyst ----\
Fundamental Analyst ---\----> Lead Strategist ----> Python computes
Sentiment Analyst ----/         |                   exact SL/TP/size
Macro Analyst -------/          v                       |
                           Verifier (reviews) <----------/
                                |
                                v
                    APPROVE --> Trade executed
                    REVISE  --> Apply changes, confidence -15%
                    VETO    --> HOLD, confidence = 0
```

---

## Tier 0: Daily Bias Engine

| Attribute | Detail |
|-----------|--------|
| **Role** | Pre-market macro strategist |
| **What it does** | Digests overnight news, macroeconomic data, central bank rhetoric, and cross-asset correlations into a cached directional bias per symbol |
| **Why** | Injected at zero latency cost into every intraday decision |
| **Default Model** | `deepseek/deepseek-r1:free` |
| **How it's run** | Celery scheduled task (`compute_daily_bias`) every 4 hours |

**Output:**
```json
{
  "bias": "BULLISH|BEARISH|NEUTRAL",
  "confidence": 0.85,
  "rationale": "Fed hawkish tone + DXY weakening...",
  "key_levels": [1.0820, 1.0950],
  "risk_events": ["US NFP @ 08:30", "ECB Speech @ 14:00"]
}
```

---

## Tier 1: Domain Analysts (Parallel)

Four analysts run in parallel, each consuming pre-computed Python analysis snapshots and returning a structured opinion.

### 1. Technical Analyst

| Attribute | Detail |
|-----------|--------|
| **Role** | Technical indicator interpreter |
| **What it analyzes** | Multi-timeframe indicators: RSI(14), EMA(9/21), ADX(14), ATR(14), Bollinger Band squeeze, signal strength, confidence |
| **What it returns** | Bias (BULLISH/BEARISH/NEUTRAL), confidence score (0.0–1.0), short reasoning, risk warning |
| **Hot path** | Yes (speed matters for intraday) |

**Free Suite Model:** `openai/gpt-oss-120b:free`  
**Production Suite Model:** `deepseek/deepseek-v4-flash`  
**Extreme Suite Model:** `openai/gpt-4o`

---

### 2. Fundamental Analyst

| Attribute | Detail |
|-----------|--------|
| **Role** | Economic event & news impact assessor |
| **What it analyzes** | Economic event risk, interest rate spreads, directional bias from scheduled events, news impact |
| **What it returns** | Bias, confidence, reasoning, risk warning |
| **Hot path** | No (off-path, runs in parallel) |

**Free Suite Model:** `meta-llama/llama-3.3-70b-instruct:free`  
**Production Suite Model:** `google/gemini-2.5-flash`  
**Extreme Suite Model:** `google/gemini-2.5-pro`

---

### 3. Sentiment Analyst

| Attribute | Detail |
|-----------|--------|
| **Role** | Market sentiment interpreter |
| **What it analyzes** | Overall market sentiment score, crowd positioning, risk appetite |
| **What it returns** | Bias, confidence, reasoning, risk warning |
| **Hot path** | Yes (speed matters) |

**Free Suite Model:** `qwen/qwen3-next-80b-a3b-instruct:free`  
**Production Suite Model:** `meta-llama/llama-3.3-70b-instruct`  
**Extreme Suite Model:** `anthropic/claude-sonnet-4.5`

---

### 4. Macro Analyst

| Attribute | Detail |
|-----------|--------|
| **Role** | Macro environment reader |
| **What it analyzes** | DXY bias, risk-on/risk-off score, rate cycle phase, cross-asset correlations |
| **What it returns** | Bias, confidence, reasoning, risk warning |
| **Hot path** | No (off-path) |

**Free Suite Model:** `deepseek/deepseek-r1:free`  
**Production Suite Model:** `openai/gpt-4o-mini`  
**Extreme Suite Model:** `openai/o3`

---

## Tier 2: Lead Strategist

| Attribute | Detail |
|-----------|--------|
| **Role** | Decision fusion engine |
| **What it does** | Fuses all 4 analyst opinions, the cached daily bias, and **RAG-retrieved similar past setups** (from the vector store) into a single trade proposal |
| **Key Rule** | Proposes approximate entry/SL/TP zones — **never computes exact prices**. Python (RiskManager + ATR) calculates exact SL/TP/position size afterwards |
| **Hot path** | Yes |

**Output Schema:**
```json
{
  "decision": "BUY|SELL|HOLD",
  "confidence": 0.87,
  "timeframe": "M5",
  "entry_zone": [1.0830, 1.0845],
  "sl_zone": [1.0820, 1.0825],
  "tp_zone": [1.0880, 1.0895],
  "position_size_pct": 1.5,
  "risk_reward": 2.0,
  "rationale": "Technical bullish with fundamental tailwind..."
}
```

**Free Suite Model:** `openai/gpt-oss-120b:free`  
**Production Suite Model:** `google/gemini-2.5-flash`  
**Extreme Suite Model:** `anthropic/claude-opus-4.1`

---

## Tier 3: Verifier (Risk Manager)

| Attribute | Detail |
|-----------|--------|
| **Role** | Ruthless risk manager |
| **What it does** | Reviews the Lead's proposal and finds flaws across fundamental and technical lines. Can **APPROVE**, **REVISE** (suggest changes), or **VETO** |
| **Checks** | Conflicting analyst opinions, poor risk/reward ratios, news proximity risk, overleveraging, counter-trend positioning, macro contradictions |
| **Can be disabled** | Yes (`verifier_enabled` setting) |
| **Can be overridden** | Yes (`verifier_can_veto` setting) |
| **Hot path** | No (off-path, can use slow reasoning model) |

**Verdict Outcomes:**

| Verdict | Action | Impact |
|---------|--------|--------|
| **APPROVE** | Trade proceeds as proposed | None |
| **REVISE** | Apply suggested changes, confidence multiplied by 0.85 | Reduced confidence |
| **VETO** | Trade becomes HOLD, confidence = 0 | Trade blocked |

**Free Suite Model:** `deepseek/deepseek-r1:free`  
**Production Suite Model:** `deepseek/deepseek-r1`  
**Extreme Suite Model:** `google/gemini-2.5-pro`

---

## Model Suite Comparison

| Function | Free (Testing) | Production (Free + Affordable) | Extreme (Best) |
|----------|:------------:|:-----------------------------:|:--------------:|
| **Technical** | `openai/gpt-oss-120b:free` | `deepseek/deepseek-v4-flash` | `openai/gpt-4o` |
| **Fundamental** | `meta-llama/llama-3.3-70b-instruct:free` | `google/gemini-2.5-flash` | `google/gemini-2.5-pro` |
| **Sentiment** | `qwen/qwen3-next-80b-a3b-instruct:free` | `meta-llama/llama-3.3-70b-instruct` | `anthropic/claude-sonnet-4.5` |
| **Macro / Daily Bias** | `deepseek/deepseek-r1:free` | `openai/gpt-4o-mini` | `openai/o3` |
| **Lead Strategist** | `openai/gpt-oss-120b:free` | `google/gemini-2.5-flash` | `anthropic/claude-opus-4.1` |
| **Verifier** | `deepseek/deepseek-r1:free` | `deepseek/deepseek-r1` | `google/gemini-2.5-pro` |

> **Custom mode:** Pick each model individually via the frontend Settings page.

---

## Feature Switches

| Setting | Default | What It Does |
|---------|---------|--------------|
| `decision_engine_version` | `v1` | `v1` = single-LLM path; `v2` = multi-agent team |
| `model_suite` | `free` | Which preset suite to use (free / production / extreme / custom) |
| `verifier_enabled` | `true` | Whether the Verifier runs at all |
| `verifier_can_veto` | `true` | Whether the Verifier can block trades |
| `analyst_parallelism` | `true` | Run 4 analysts in parallel (faster) or sequentially |
| `daily_bias_enabled` | `true` | Whether to compute and cache daily bias |

---

## Where To Change Models

1. Go to **Settings** in the frontend
2. Under **AI Trading Team (v2)**, select:
   - `v1 Single LLM` — one model does everything
   - `v2 Multi-Agent Team` — 4 analysts + lead + verifier
3. Pick a **Model Suite**: Free, Production, Extreme, or Custom
4. Save. The backend reads these from the database on every decision cycle.

---

## Source Files

| File | Purpose |
|------|---------|
| `app/ai/team/orchestrator.py` | Pipeline orchestrator — wires all tiers together |
| `app/ai/team/analyst.py` | Domain analysts — technical, fundamental, sentiment, macro |
| `app/ai/team/lead.py` | Lead Strategist — fuses opinions + RAG + bias |
| `app/ai/team/verifier.py` | Verifier / Risk Manager — reviews and vetoes |
| `app/ai/team/daily_bias.py` | Daily Bias Engine — pre-market macro assessment |
| `app/ai/suites.py` | Suite definitions: free / production / extreme / custom |
| `app/ai/openrouter_client.py` | OpenRouter API client with failover |
| `app/ai/model_router.py` | Latency-aware model rotation and failover |
| `app/tasks/analysis_tasks.py` | Celery task that runs the full pipeline |
| `app/tasks/execution_tasks.py` | Celery task that computes daily bias |
| `app/config.py` | Environment-level defaults (now empty for model fields) |
| `app/services/settings_service.py` | Database settings storage & retrieval |

---

## Quick Model Reference Card

### Free Tier (Testing)
> Fast, zero cost. Good for development and testing.

| Function | Model |
|----------|-------|
| Technical | openai/gpt-oss-120b:free |
| Fundamental | meta-llama/llama-3.3-70b-instruct:free |
| Sentiment | qwen/qwen3-next-80b-a3b-instruct:free |
| Macro / Bias | deepseek/deepseek-r1:free |
| Lead | openai/gpt-oss-120b:free |
| Verifier | deepseek/deepseek-r1:free |

### Production Tier (Free + Affordable)
> Balanced quality and speed. Recommended for live trading.

| Function | Model |
|----------|-------|
| Technical | deepseek/deepseek-v4-flash |
| Fundamental | google/gemini-2.5-flash |
| Sentiment | meta-llama/llama-3.3-70b-instruct |
| Macro / Bias | openai/gpt-4o-mini |
| Lead | google/gemini-2.5-flash |
| Verifier | deepseek/deepseek-r1 |

### Extreme Tier (Best Regardless of Price)
> Maximum reasoning quality. Higher latency and cost.

| Function | Model |
|----------|-------|
| Technical | openai/gpt-4o |
| Fundamental | google/gemini-2.5-pro |
| Sentiment | anthropic/claude-sonnet-4.5 |
| Macro / Bias | openai/o3 |
| Lead | anthropic/claude-opus-4.1 |
| Verifier | google/gemini-2.5-pro |

---

*Generated with [Devin](https://cli.devin.ai/docs)*
