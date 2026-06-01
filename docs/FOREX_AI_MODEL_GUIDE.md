# Chat Archive: AI Models for Automated Forex Trading on OpenRouter

This document compiles the complete discussion, structural blueprints, and model assessments for building an automated Forex, Crypto, and Index trading script using OpenRouter.ai models across scalping, day trading, and swing trading timeframes.

---

## Part 1: Initial Analysis & Model Categorization

Using Large Language Models (LLMs) for Forex trading requires models that can handle a mix of complex quantitative patterns, broad macroeconomic logic, and market psychology. When trading Forex, you generally need models that excel at three things:

1. **Technical Analysis:** Processing tabular price feed data, mathematical indicator values (RSI, MACD), or raw price text arrays to look for patterns.
2. **Fundamental Analysis:** Digesting long-form central bank statements (Fed, ECB), interest rate decisions, and economic calendar metrics (NFP, CPI).
3. **Sentimental Analysis:** Scanning financial news feeds, geopolitics, and market commentary to gauge risk-on/risk-off positioning.

OpenRouter provides access to excellent models for this, categorized into **completely free tiers** and **affordable paid tiers** that offer frontier-level capabilities.

### 1. Best Free AI Models on OpenRouter

OpenRouter hosts a rotating selection of free models (often subsidized by providers or the platform). For trading analysis, you need models with strong reasoning capabilities, not just small chat variants.

* **DeepSeek V3 (Free / Low-Cost Options)**
    * **Why it fits Forex:** DeepSeek V3 is a highly advanced Mixture-of-Experts (MoE) model. It performs remarkably well in pattern recognition and code generation.
    * **Trading Strengths:** It is highly competent at writing and debugging trading scripts (like MQL5 for MetaTrader, or Python backtesting scripts). Its quantitative reasoning makes it excellent at processing structured technical data or multi-layered fundamental reports.
* **Qwen 2.5 72B Instruct (Free/Subsidized Endpoints)**
    * **Why it fits Forex:** Developed by Alibaba, the Qwen 2.5 series possesses world-class multi-lingual and strong mathematical capabilities.
    * **Trading Strengths:** It is one of the absolute best open-weights models for structural analysis. If you pass it formatted economic calendars or ask it to parse financial news for sentiment, it accurately categorizes market impact (e.g., *Bullish/Bearish/Neutral* with a confidence score) without hallucinating metrics.
* **Meta: Llama 3.1 / 3.3 70B Instruct (Free Endpoints)**
    * **Why it fits Forex:** These models are highly generalized workhorses with extensive context windows (up to 128K tokens).
    * **Trading Strengths:** Perfect for **Fundamental Analysis**. You can feed it entire PDFs of Federal Reserve FOMC meeting minutes or central bank press conference transcripts. It will accurately extract shifted rhetoric (e.g., a transition from "hawkish" to "dovish") across dense bodies of text.

### 2. Best Affordable Paid Models

While free models are great for prototyping or basic daily summaries, Forex trading often requires **advanced multi-step reasoning** (deciding *if* a technical setup aligns with a fundamental bias). For live trading logic, these highly affordable paid models offer vastly superior accuracy.

| Model | Avg. Input Cost (per 1M tokens) | Avg. Output Cost (per 1M tokens) | Primary Forex Superpower |
| :--- | :--- | :--- | :--- |
| **DeepSeek R1** | ~$0.55 | ~$2.19 | Advanced multi-step trading logic, quantitative chain-of-thought, and deep statistical interpretation. |
| **Google Gemini 1.5/2.5 Flash** | ~$0.075 | ~$0.30 | Massive context window (1M+ tokens) for scanning multi-day news feeds or continuous tick data cheaply. |
| **GPT-4o mini** | ~$0.15 | ~$0.60 | Speed, structured JSON outputs, and reliable API consistency for execution pipelines. |

* **DeepSeek R1 (The Alpha Model)**
    * **The Trading Edge:** R1 is a "reasoning" model that uses a native chain-of-thought process before replying. If you ask R1: *"Analyze EUR/USD given this technical breakout but factoring in an upcoming higher-than-expected US CPI print,"* it will systematically think through the market mechanics out loud. It maps the liquidity grabs, potential central bank responses, and sentiment shifts before giving its conclusion, drastically reducing impulsive or flawed analysis.
* **Google Gemini Flash (The Macro Scan)**
    * **The Trading Edge:** Its massive context window allows you to drop days' worth of news scrapings, order book depth charts, and technical charts simultaneously. It acts as a highly affordable data aggregator to determine overall market sentiment or build a comprehensive morning dashboard.

### Important Technical Limitations & Advice
1. **The "Live Data" Trap:** LLMs are static. They **do not know today's live price** unless you pass it to them via an API call in your code. You must fetch the technical data (OHLCV, indicators) or news via an external system and pipe it into the OpenRouter prompt.
2. **Hallucinations with Numbers:** Standard models can occasionally scramble floating-point numbers when calculating stop-losses or position sizes. For precise mathematical risk management, always rely on native code execution (Python/MQL5) rather than asking the AI to do mental math.

---

## Part 2: Automated Script Strategy (Majors, Crypto, Indices)

Transitioning from manual analysis to an **automated script** completely changes your model selection criteria. Because you are targeting **Scalping and Day Trading** across Majors, Crypto, and Indices, your automated script requires a layout built for **low latency, structural reliability (JSON formatting), and robust logic handling.**

If a script takes 30 seconds to run deep reasoning, the scalping opportunity on a 5-minute chart is completely gone. Therefore, your automation strategy should split tasks by speed and reasoning depth.

### 1. Automated Scalping & Day Trading Blueprint

For active intraday execution via an automated script, the architecture requires specific endpoints. Below are the best free and low-cost models optimized for programmatic pipelines.

#### Best Free Models for Automated Pipelines
To use these free endpoints securely in a script, filter your OpenRouter payload using the `:free` suffix in the model ID.

* **`deepseek/deepseek-r1:free` (Best Free Logic / Sentiment)**
    * **The Fit:** This gives you access to full chain-of-thought logic without token costs.
    * **Automation Role:** Excellent for processing combined daily sentiment inputs or high-impact news releases (e.g., NFP, CPI) before the market opens to establish your daily "bias."
    * **Script Limitation:** It can be slow to generate reasoning tokens, making it a bottleneck if placed directly inside a live tick-loop.
* **`openai/gpt-oss-120b:free` (Best Free Technical/JSON parsing)**
    * **The Fit:** A massive open-weights Mixture-of-Experts (MoE) model built natively for agentic workflows.
    * **Automation Role:** It features excellent native tool-calling and structured outputs. When your script needs to parse an array of technical data (like a string of RSI, MACD, and moving average values) and return a precise JSON object like `{"signal": "BUY", "confidence": 0.82}`, this model handles the structural formatting without throwing syntax errors.

#### Best Affordable Paid Models (Highly Recommended for Active Scripts)
When running live capital on short timeframes, reliance on the free tier risks hitting occasional provider rate limits (typically 20 requests per minute on free endpoints) right when a trade needs to exit. These paid models cost pennies but guarantee immediate execution.

| Model ID | Input Cost (per 1M tokens) | Output Cost (per 1M tokens) | Strengths for Short Timeframes |
| :--- | :--- | :--- | :--- |
| **`google/gemini-2.5-flash`** | ~$0.075 | ~$0.30 | **Sub-second latency.** Ideal for rapid calculation passes on 5m/15m charts. |
| **`deepseek/deepseek-v4-flash`** | ~$0.098 | ~$0.197 | Extreme throughput. Perfect for multi-pair scanning (scanning 5 Forex pairs + Bitcoin + US30 concurrently). |
| **`openai/gpt-4o-mini`** | ~$0.15 | ~$0.60 | Industry standard for structured JSON output stability in execution loops. |

### 2. Advanced Swing Trading Setup (Later Stage)

When you eventually expand your script to handle swing trading (holding positions over days or weeks), latency matters less, while **context capacity and macroeconomic data retention** matter much more.

* **The Free Heavyweight: `meta-llama/llama-4-maverick:free` (or Llama 3.3 70B free variants)**
    * **Why it works:** Features a huge context window.
    * **Swing Strategy:** Your script can pull the last **30 days of market news**, the latest central bank press release transcripts, and long-term daily technical data arrays, and feed them all into a single prompt. It is highly capable of identifying complex cross-market correlations (e.g., how a shift in US Treasury yields is likely to impact the USD/JPY and the S&P 500 over the next two weeks).
* **The Paid Powerhouse: `deepseek/deepseek-r1` (Paid Tier)**
    * **Cost:** ~$0.70 /M Input | ~$2.50 /M Output.
    * **Swing Strategy:** Paid R1 allows high reasoning budgets. You can use it as a "Risk Manager" agent in your code. Before a swing trade is logged to the database, the script passes the trade details to R1 with the instruction: *"Find the flaws in this setup across fundamental and technical lines."* The model will systematically tear down the trade thesis, helping you avoid over-leveraged long-term mistakes.

### 3. How to Structure Your Automation Prompts

To make these models profitable and stop them from hallucinating trade levels, **never send raw paragraphs of text.** You must force structured inputs and outputs using JSON formatting.

#### System Prompt Template
```
You are a deterministic financial analysis engine executing high-frequency data parsing. 
You do not use conversational filler. You analyze inputs purely based on mathematical indicators, order flow, and specified fundamental sentiment. 
You must output exclusively in valid JSON format matching the schema requested.
```

#### User Input Schema (What your script sends)
```json
{
  "ticker": "EUR_USD",
  "timeframe": "M5",
  "technical_indicators": {
    "ema_200": 1.0850,
    "current_price": 1.0862,
    "rsi_14": 68.5,
    "macd_signal": "bullish_crossover"
  },
  "market_sentiment": "Risk-On (Equities surging, Dollar Index weakening)",
  "upcoming_news_impact": "High (US Core PCE in 45 minutes)"
}
```

#### Required Output Schema (What the model returns)
```json
{
  "market_bias": "BULLISH",
  "confidence_score": 0.78,
  "reasoning_short": "Price holding above 200 EMA with bullish MACD momentum matching broader risk-on sentiment.",
  "risk_warning": "PCE release in 45m introduces severe volatility risk. Tight trailing stops required."
}
```

By keeping the input and output data structured, models like Gemini 2.5 Flash can process the request in milliseconds, giving your script clean data to instantly pass into your execution broker's API.
