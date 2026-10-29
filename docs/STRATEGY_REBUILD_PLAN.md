# Strategy Rebuild Plan — Evidence-Based Tournament (Phase 7)

**Status:** DRAFT — awaiting approval
**Date:** 2026-10-21
**Author:** Devin (persona: forex trading scholar / quant practitioner)
**Supersedes:** Phase 6 paper-forward validation (halted 2026-09-01 at -$20.61 / 13 trades)

---

## 0. Executive summary

The current system is not broken; it is **correctly halted**. Phase 6 proved what the
standalone backtest already showed: an indicator-soup M5 scalper (EMA9/21 + ADX + RSI)
on EURUSD has **negative expectancy after spread** (33.4% WR over 6,399 backtest trades;
-$20.61 live over 13). The LLM layer did not rescue it, and could not have — three of its
six models are now dead or misconfigured on OpenRouter.

This plan replaces the signal layer with a **parallel tournament of evidence-backed
rule strategies** across timeframes and a majors basket, demotes the LLM team to
**regime classifier + per-candidate filter/veto** (where it demonstrably adds value), and
defines a **statistical promotion bar** so "ready for real money" is a number, not a feeling.

Your stated goals, which this plan is built around:

| Goal | Your answer | Design consequence |
|---|---|---|
| Primary job | Learn before real money | Instrumentation and honest stats matter more than P&L this phase |
| Timeframe | Try several, pick the best | Parallel strategy x timeframe tournament with per-variant accounting |
| LLM role | Filter/veto + regime classifier | Rules generate candidates; LLM never originates direction |
| Budget | ~$10-50/mo | Mid-tier non-reasoning models on hot path, one reasoning model for the verifier |
| Success bar | Statistical proof | >=300 trades/variant, positive expectancy after costs, DD <10%, t-stat > 2 |
| Universe | Majors basket | EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF (+XAUUSD, flagged - see 8.1) |
| Gates | Asked for recommendation | Strip to minimum; log everything we stop enforcing |

---

## 1. Research findings

### 1.1 Live audited track records (MQL5 Signals leaderboard, pulled 2026-10-21)

The MQL5 Signals service publishes broker-verified live statistics. I pulled three views:
*Reliability* (preset=11), *Intraday* (preset=12), and the honest one - **sorted by weeks
live, descending** - which strips survivorship bias from the growth-sorted front page.

**What the longest-lived profitable signals (200+ weeks) have in common:**

| Signal | Weeks | Trades | WR | PF | Exp. payoff | DD | Hold | Notes |
|---|---|---|---|---|---|---|---|---|
| NoPain MT5 | 261 | 5,913 | 64% | 1.70 | $0.68 | 21% | **1 day** | Single pair (AUDCAD), 5 trades/wk, Sharpe 0.15, 2%/mo |
| Deux ex machina | 285 | 1,910 | 73% | 1.87 | 3.78 EUR | 26% | - | ~7 trades/wk |
| Relax EA | 311 | 2,083 | 76% | 1.49 | 0.79 EUR | 33% | - | ~7 trades/wk |
| Tharos II | 282 | 5,722 | 68% | 1.53 | 3.29 EUR | 47% | - | |
| Scalp IC Markets MT5 | 255 | 2,605 | 72% | 1.60 | 0.18 EUR | 33% | - | "Scalp" but payoff near zero |
| TTM Stable Swing | 267 | 8,331 | 75% | 1.66 | 1.51 AUD | 80% | - | Swing label, huge DD |
| Longterm ICM | 325 | 9,377 | 74% | 1.21 | 3.68 EUR | 28% | - | |

**And the ones that survived 200+ weeks but *lost*:** FxPro (-63%, PF 1.01), FurkoSig
(-62%, PF 0.93), ActivTrades (-32%, PF 0.96), DIAMOND (-32%, 28% WR), TCFX Dark Phoenix
(-18%), Bereza (-10%, 90% WR but PF 0.67 - the classic martingale signature).

**Pattern extraction:**

1. **Profit factor 1.5-1.9 is the realistic ceiling for durable retail systems.** Nobody
   above 2.0 has survived more than ~100 weeks on this board. PF 3+ on the front page is
   always young (<80 weeks), gold-only, or 1:500 leverage with 50%+ DD.
2. **Win rate 63-76% with avg loss ~ avg win** (NoPain: +$2.57 / -$2.68) - i.e., ~1:1 RR
   with a real directional edge, *not* the 1:2 "let winners run" textbook profile and
   *not* the 90% WR / PF<1 grid-martingale profile.
3. **Low trade frequency.** 3-7 trades per week. Not 3-7 per day.
4. **Hold time of hours to a day**, not minutes. The one self-described "Scalp" survivor
   has expected payoff of 0.18 EUR - treading water after costs.
5. **Single pair or tight basket.** The most durable one trades one cross exclusively.
6. **Sharpe is low everywhere (0.10-0.15).** These are not hedge funds; a retail "winning
   system" is a modest, persistent edge compounded with discipline.
7. **The front-page darlings are gold.** MSC SuperGold Pro: 16,932% growth, 76% WR -
   and *-33.75% last month*, 53% DD, "A large drawdown may occur on the account again"
   warning banner, 20% fixed stop. That is the house's own description of what a
   high-growth XAUUSD scalper looks like after the honeymoon.

### 1.2 MQL5 article: *Behavioural Cloning in a Live Trading System* (Tuna, Oct 2026)

Directly relevant - it is almost a mirror of this project's failure modes:

- PPO agent on XAUUSD M15, **763 live demo trades, PF 1.05, t-stat 0.55** -
  indistinguishable from zero. ("Gold's direction on M15 was not predictable from the
  features I had.")
- A self-learning loop weighted by own-trade outcomes **collapsed the policy to HOLD**
  (48% -> 82% hold share; 12 of the final models stopped trading entirely). This is the
  same mechanism as our pattern filter: a 6-trade London sample blocks London, so the
  sample can never update, so London stays blocked.
- Simulator transaction costs were **~85x lower than reality**. Real exit slippage was
  ~$4.85 per exit, **a third of realised profit**. His conclusion: the one thing live
  data reliably teaches is *what it costs to act*, not where price is going.

Takeaways baked into this plan: (a) no self-reinforcing filters on thin samples;
(b) measure real spread/slippage per session and feed it back into the backtest;
(c) a 700+ trade sample at PF ~1.05 is "no edge", so our promotion bar must be stricter
than "positive P&L".

### 1.3 Academic / replicated evidence (primary literature)

| Strategy family | Evidence strength | Key sources | Horizon where it works |
|---|---|---|---|
| **Time-series momentum / trend-following** | **Strongest in all of TA.** Replicated across 50+ markets, 100+ years | Moskowitz, Ooi & Pedersen (2012, JFE); Hurst, Ooi & Pedersen "A Century of Evidence on Trend-Following" (2017); Menkhoff, Sarno, Schmeling & Schrimpf "Currency Momentum Strategies" (2012, JFE) | D1 / H4 (1-12 month lookbacks; shorter works but decays) |
| **Carry / rate-differential tilt** | Strong, decades | Burnside et al. (2011); Menkhoff et al. (2012) "Carry Trades and Global FX Volatility" | Positional bias, weeks-months. Not a signal - a *filter* |
| **Breakout / channel (Donchian)** | Good; this is how trend-following is operationalised | Turtle rules; Faber; most CTA literature | H4 / D1 |
| **Intraday session effects** | Moderate-good. Volatility clustering around London/NY open is robust; the *tradeable* edge is thinner | Andersen & Bollerslev (1998) intraday periodicity; Breedon & Ranaldo (2013) "Intraday Patterns in FX Returns and Order Flow"; Ranaldo (2009) | M15-H1, 07:00-10:00 and 13:00-16:00 UTC windows |
| **Post-announcement drift** | Moderate | Evans & Lyons; Andersen et al. (2003) "Micro Effects of Macro Announcements" | 15-60 min *after* release, not during |
| **Short-term mean reversion** | Weak-to-mixed in FX after costs | Mostly equity literature (Lehmann 1990); FX intraday MR is a liquidity-provision edge that retail cannot access | - |
| **EMA cross / RSI OB-OS / MACD on M1-M15** | **Negative after data-snooping correction and costs** | Brock, Lakonishok & LeBaron (1992) -> Sullivan, Timmermann & White (1999) "Data-Snooping, Technical Trading Rule Performance"; Park & Irwin (2007) survey | Our own backtest: 33.4% WR, -$2,815 |

**Cost arithmetic for M5 scalping on EURUSD** (why the evidence is so one-sided):
typical retail effective spread ~0.8-1.2 pips round-trip. At an 8-pip target / 6-pip stop,
spread is 12-20% of every outcome. You need ~58% WR at 1.3R just to reach zero. The
longest-lived MQL5 "scalper" (Scalp IC Markets) has 72% WR and still nets 0.18 EUR/trade.
Meanwhile at an H4 Donchian entry with a 40-pip stop, spread is 2.5% of the outcome.

### 1.4 LLM model landscape (live OpenRouter catalog, pulled 2026-10-21)

Nearly every current flagship is a **reasoning model** that emits a `reasoning` field
before `content`. With our `max_tokens=256/384` JSON-only prompts, the budget is consumed
by chain-of-thought and `content` comes back `None`. That is exactly what killed the lead
strategist (`deepseek-v4-flash`: `finish_reason=length`, content `None`, 384 reasoning
tokens). Verified by direct API call.

Dead/broken in current config: `deepseek/deepseek-r1` (404, removed),
`nvidia/nemotron-3-super-120b-a12b:free` (404), `openrouter/owl-alpha` (removed),
`deepseek/deepseek-v4-flash` (alive but reasoning-starves JSON).

Candidates verified alive with `response_format` + `structured_outputs` support:

| Role | Pick | Type | ~Blended $/M | Why |
|---|---|---|---|---|
| Regime classifier (once/session/pair) | `qwen/qwen3-next-80b-a3b-instruct` | non-reasoning | 0.60 | Cheap, schema-compliant, fast |
| Technical analyst | `qwen/qwen3-next-80b-a3b-instruct` | non-reasoning | 0.60 | Same; this role is now descriptive, not decisive |
| Fundamental analyst | `google/gemini-2.5-flash` | reasoning (works) | 1.40 | Already returns good opinions in logs; keep |
| Sentiment analyst | `meta-llama/llama-3.3-70b-instruct` | non-reasoning | 0.21 | Already works; keep |
| Macro analyst | `openai/gpt-5-nano` w/ `reasoning_effort: low` | reasoning | 0.22 | Replaces gpt-4o-mini at lower cost; supports effort cap |
| **Lead / filter** | `moonshotai/kimi-k2-0905` | **non-reasoning** | 1.55 | Best instruction/JSON follower in catalog without CoT tax; fallback `deepseek/deepseek-chat-v3.1` |
| **Verifier** | `deepseek/deepseek-r1-0528` | reasoning | 1.33 | Off hot path; this is the one role where thinking is the point. Fallback `google/gemini-2.5-pro` |

Estimated cost at 6 pairs x ~20 cycles/day: **$20-35/month**. Inside budget.

Required client changes regardless of model: pass OpenRouter `reasoning: {effort: "low"}`
(or `{enabled: false}` for non-reasoning routes), raise `max_tokens` to 1024 on analysts /
1536 on lead, prefer `structured_outputs` with an explicit JSON schema over
`response_format: json_object`, and treat `content is None` as a hard failure that logs
`finish_reason` + `usage.completion_tokens_details.reasoning_tokens` rather than silently
parsing `{}` into HOLD.

---

## 2. Design principles (derived from the evidence)

1. **Rules originate direction; the LLM may only say no.** Every BUY/SELL comes from a
   deterministic, backtestable rule with a named variant ID. The LLM team filters
   (regime mismatch, news risk, macro contradiction) and can veto, never flip or invent.
2. **Fewer, larger, longer trades.** Target 3-10 candidates/day across the whole
   tournament, holding hours to days. Spread must be <5% of the stop distance.
3. **Every variant is an experiment with a pre-registered hypothesis, sample size, and
   kill criterion.** No variant is tuned mid-flight; if it fails, it is retired and a new
   variant ID is registered.
4. **Nothing self-reinforcing on thin data.** Learned priors (pattern stats, XGB score)
   are logged and shown to the LLM as context; they do not gate.
5. **Measure costs for real.** Record requested vs filled price, spread at decision time,
   and session for every entry and exit. Feed the measured distribution back into the
   backtest engine (Tuna's "reconciler").
6. **Promotion is statistical, not emotional.** See section 6.

---

## 3. Tournament design

### 3.1 Strategy families and variants

Each row is a registered `variant_id`. All variants use ATR-based stops and fixed-dollar
risk so expectancy is comparable across pairs/timeframes.

| ID | Family | Timeframe | Entry rule | Exit rule | Hypothesis | Evidence |
|---|---|---|---|---|---|---|
| `TF-D1-DON20` | Trend-following | D1 | Close breaks Donchian(20) high/low **and** ADX(14) > 20 **and** close on correct side of EMA(50) | Opposite Donchian(10) break or 2.0 ATR trailing | Classic Turtle; the textbook strongest-evidence setup | MOP 2012; Hurst 2017 |
| `TF-H4-DON20` | Trend-following | H4 | Same rules on H4 | Same | Does the D1 edge survive at 6x the frequency? | Menkhoff 2012 (decays with horizon) |
| `TF-H1-DON55` | Trend-following | H1 | Donchian(55) break + ADX>25 + D1 trend agreement (EMA50 slope) | Donchian(20) opposite / 2 ATR trail | Multi-TF alignment version; tests whether H1 is usable with a D1 filter | Practitioner MTF consensus |
| `SB-M15-LDN` | Session breakout | M15 | Asian range (00:00-07:00 UTC) high/low broken by a closed M15 candle during 07:00-10:00 UTC; range must be >= 0.5 ATR(D1) and <= 1.5 ATR(D1) | TP = 1.0x range, SL = opposite side of range (max 1.5R), hard exit 12:00 UTC | London-open volatility expansion is the best-documented intraday periodicity | Andersen & Bollerslev 1998; Breedon & Ranaldo 2013 |
| `SB-H1-NYO` | Session breakout | H1 | London-session range (07:00-12:00) broken during 13:00-15:00 UTC | TP 1.0x range, SL opposite side, hard exit 20:00 UTC | NY-open variant | Same |
| `ND-M15-DRIFT` | Post-news drift | M15 | 15 min after a high-impact release for either currency, enter in the direction of the first 15-min candle **if** that candle is >= 1.0 ATR(M15 x 4) | TP 1.5R, SL at the pre-release price, time-stop 90 min | Capture drift, avoid the latency war during the spike | Andersen et al. 2003; Evans & Lyons |
| `MR-H1-BBFADE` | Mean reversion (**control**) | H1 | Close outside Bollinger(20, 2.5) **and** RSI(14) > 75 / < 25 **and** ADX < 20 (ranging only) | TP = BB midline, SL 1.5 ATR | Expected to lose or tread water. Included as the null arm so the tournament can show it discriminates | Weak FX evidence |
| `LEGACY-M5-EMA` | Baseline (**control**) | M5 | The existing EMA9/21 + ADX>15 + RSI rule, unchanged | Existing 1.5/2.5 ATR | The thing we already know loses; keeps running ungated at minimum size as the reference | Our own backtest |

Eight variants x 6 pairs = 48 (variant, pair) cells. Not every cell will fire daily.
Expected tournament-wide frequency: roughly 5-12 candidates/day, of which the LLM filter
passes maybe half.

### 3.2 Universe

FX basket: `EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF`.

**XAUUSD: in, but restricted** (approved decision #1). Gold's daily ATR% is ~2-3x the FX
majors, it is driven by real rates / risk-off flows rather than rate differentials, and
the MQL5 evidence shows it is where high-growth retail systems blow up (53% DD,
-34%/month on the current #1). Its one superpower is that it *trends* hard. Therefore:
XAUUSD runs **only** `TF-D1-DON20` and `TF-H4-DON20`, is excluded from SB-*/ND-*/MR-*
variants, gets its own -$40 kill cap, and is **reported as a separate bucket** in all
variant statistics so gold variance cannot contaminate the FX majors' numbers.
Pair economics (point value, typical spread, pip definition) are recorded per-instrument
at decision time - no EURUSD pip assumptions leak into gold math.

### 3.3 Per-variant risk and lifecycle

- **Fixed risk per trade: $5** (not %), so every variant's expectancy is in identical
  units. Position size derived from ATR stop distance.
- **Account-level caps unchanged** (daily 3%, weekly 6%, 5 consecutive losses).
- **Variant kill criteria (auto-retire, no human in loop)** - a sequential screen,
  designed to kill cheap losers fast and let evidence accumulate on survivors
  (approved decision #4):
  - realised P&L <= -$40 (**-8R**) at any point. At ~50% WR / ~1:1 payoff this needs a
    decisively bad run; a fair coin-flip reaches -8R only ~35% of the time.
  - >= 30 trades and expectancy < 0. Point-estimate kill, not significance - we are not
    proving it loses, we are refusing to keep paying to find out.
  - >= 60 trades and PF < 1.15. The "show real edge" bar; a null variant survives it
    only ~25-30% of the time, and survivors still face the real bar at 300 trades.
- **Variant promotion criteria -> "candidate for live":** see section 6.
- Retired variants keep their data; they can be re-registered under a new ID with a
  documented change. No in-place tuning.

### 3.4 Gate stack (final)

| Gate | Status | Rationale |
|---|---|---|
| Phase 6 halt | **Replaced** by per-variant kill criteria + account caps | It did its job; the tournament has its own stop |
| News halt (15 min before / 30 after high-impact) | **Keep, hard** | Only universally-agreed negative-edge action. `ND-M15-DRIFT` is the one variant explicitly allowed to arm *after* the window |
| Price gate | **Keep** | Harmless; skips redundant cycles |
| Risk manager (sizing, daily/weekly, consec losses, spread check, correlation, DD) | **Keep** | Core capital protection |
| XGB entry gate | **Demote to logged feature** | June model trained on negative-edge data; blocks 100% of candidates. Score is written to each decision for later evaluation |
| Pattern filter (hard block) | **Demote to LLM context** | Self-sealing on 6-trade samples (Tuna's HOLD-collapse). Priors shown in the lead prompt, never enforced |
| 21:00 UTC EOD no-new-entries | **Make per-variant** | Correct for session/intraday variants; wrong for D1/H4 trend variants that must hold overnight |
| Overnight cutoff / exit re-eval | Keep disabled for trend variants, enable for session variants | Trend edges *are* the overnight moves |

### 3.5 LLM team - new responsibilities

```
once per pair per session (3x/day):
  RegimeClassifier -> {regime: trending_up|trending_down|ranging|volatile_news, confidence}
    - enables/disables variant families: TF-* need trending; MR-* need ranging;
      SB-* and ND-* ignore regime

per rule-generated candidate:
  Analysts (fund, sent, macro) -> opinions (as today, cheaper models)
  Lead/Filter -> {verdict: PASS|VETO, confidence, rationale}
    - input: candidate (variant, direction, entry/SL/TP already computed by Python),
      regime, analyst opinions, upcoming calendar, pattern priors (context only)
    - may VETO; may *not* change direction, levels, or size
  Verifier (r1-0528) -> second opinion on PASS only; VETO power retained
```

Decision rows gain: `variant_id`, `regime`, `llm_verdict`, `xgb_score` (logged),
`pattern_prior_snapshot` (logged), `spread_at_decision`, `requested_price`.
Trade rows gain: `variant_id`, `fill_slippage_pips`, `exit_slippage_pips`,
`spread_at_entry`, `spread_at_exit`.

A **shadow arm** runs in parallel: every rule candidate is *also* recorded as if executed
with no LLM filter (paper-on-paper). After 300 trades we can answer the question that
justifies the LLM budget at all: *does the filter improve expectancy over the raw rules?*

---

## 4. Implementation phases

### Phase 7.0 - Plumbing (1-2 days; no strategy change yet)

1. **Model suite swap** (`backend/app/ai/suites.py`): add `production_v2` suite per
   section 1.4; set `model_suite=production_v2`. Prune dead IDs from `ai_model`,
   `ai_model_pool`, and the `free` suite (`owl-alpha`, `nemotron-3-super`).
2. **OpenRouter client hardening** (`backend/app/ai/openrouter_client.py`):
   - accept a per-call `reasoning` dict; default `{"effort": "low"}` on hot-path roles,
     omit for the verifier;
   - raise `max_tokens` (analysts 1024, lead 1536, verifier 2048);
   - prefer `structured_outputs` with explicit schema when `supported_parameters`
     advertises it (cache `/models` daily);
   - **fail loudly** on `content is None` / `finish_reason == "length"`: log model,
     `reasoning_tokens`, and raise so the role's documented fallback fires with a
     rationale, instead of `{}` -> silent HOLD(0.0).
3. **Startup model-health probe**: on worker boot and daily, hit each configured model with
   a 20-token JSON ping; mark dead models in Redis; router skips them. Alert on failure.
4. **Data fixes**: `NewsService.get_latest_headlines` (daily bias has been `null` for
   weeks); FRED `DFEDTAR` -> `DFEDTARU`/`FEDFUNDS` (JSON decode failure every cycle);
   confirm Myfxbook 403 -> COT proxy path is intentional.
5. **Phase 6 stays ON through 7.0 and 7.1 dev** (`phase6_active=true`). The halt blocks
   *execution* but not decision-generation — every new-model decision is logged in
   production as `RISK BLOCKED: PHASE 6 HALT` with zero trades firing. That turns the
   existing halt into a free read-only mode for validating the fixed AI layer live.
   `phase6_active=false` flips only at Phase 7.3 when the tournament opens. Record the
   Phase 6 result in `AGENTS.md`.

Exit criterion: one full `run_full_analysis` cycle where the lead returns a non-empty
rationale and the verifier returns a real verdict; zero 404s in a 24h log window.

### Phase 7.1 - Variant engine (3-5 days)

1. **Schema**: Alembic migration adding `variant_id` (+ slippage/spread columns) to
   `trades` and `ai_decisions`; new `strategy_variants` table (id, family, timeframe,
   params JSON, status active|retired|promoted, registered_at, retired_at, kill_reason).
2. **`backend/app/strategies/`** package: `base.py` (`Candidate` dataclass:
   variant_id, symbol, direction, entry, sl, tp, atr, timeframe, rationale),
   `trend.py` (Donchian/ADX/EMA family), `session.py` (range-breakout family with the
   DST-aware session clock), `news_drift.py`, `mean_reversion.py`, `legacy.py` (wraps
   `_generate_rule_based_decision`). Each exposes `generate(symbol, candles_by_tf,
   calendar, now) -> list[Candidate]`.
3. **Candle access**: `technical.py` already builds multi-TF indicators; extend
   `aggregator.gather_all` to fetch D1/H4/H1/M15 for all six pairs (currently
   scalping-centric). Cache per cycle.
4. **Pipeline rewire** in `analysis_tasks.run_full_analysis`: replace the
   "LLM decides" block with: `candidates = engine.generate_all()` -> regime gate ->
   news gate -> LLM filter -> risk manager -> executor. Shadow-record every candidate
   pre-filter.
5. **Per-variant accounting**: `VariantMonitor` task (every 30 min) computes per-variant
   trades, WR, PF, expectancy, max DD, t-stat, 90% CI on PF; applies kill criteria;
   writes a `variant_stats` snapshot; notifies on retire/promote.
6. **Execution reconciler**: record requested price at order send; on fill/close, compute
   slippage from MT5 deal history; store per trade. Nightly job aggregates spread/slippage
   by pair x session into `execution_costs` for the backtest engine.

Exit criterion: all 8 variants registered; each has produced at least one candidate in
the standalone backtest (technical-only mode) without error; dashboard shows per-variant
table.

### Phase 7.2 - Backtest sanity pass (1-2 days, before going live-paper)

Run each variant through `run_backtest_standalone.py` in technical-only mode **with the
measured execution costs** from Phase 6/7 fills (not the simulator defaults). Purpose is
*not* to pick a winner (per `AGENTS.md`, this backtest cannot do that) but to:
- catch rule bugs (e.g., breakout firing on the wrong side),
- confirm realistic trade frequency per variant,
- confirm the control arms behave as expected (LEGACY negative, MR flat-to-negative).

Any variant that is *wildly* positive in backtest is a red flag for look-ahead; audit it.

### Phase 7.3 - Live paper tournament (8-16 weeks)

Start all variants. Weekly automated report (variant table + equity curves + shadow-arm
comparison). Human reviews only: (a) kill/promote notifications, (b) the week-4 and week-8
checkpoints below. No parameter changes mid-tournament.

- **Week 4 checkpoint**: are candidate frequencies in the expected range? Is the LLM
  veto rate sane (20-60%)? Are controls losing? If LEGACY is *winning*, something is
  wrong with the new variants' execution - stop and audit.
- **Week 8 checkpoint**: first variants should approach 100+ trades. Review which
  families/timeframes are alive. Decide whether to register second-generation variants
  (e.g., `TF-H4-DON20` with a different ADX threshold) as *new* IDs.

### Phase 7.4 - Promotion and retrain

When a variant meets section 6: freeze it, run 4 more weeks as sole-focus confirmation,
then (your call) move to micro-lot live. In parallel, **retrain the entry-quality model on
live-labelled tournament trades** - that is the correct training set the June model never
had. Evaluate it as a shadow score for another 100 trades before it is allowed to gate.

---

## 5. Model suite and cost

| Role | Model | reasoning param | max_tokens | Calls/day (6 pairs) | Est. $/mo |
|---|---|---|---|---|---|
| Regime | qwen3-next-80b-instruct | n/a | 512 | 18 | <1 |
| Technical | qwen3-next-80b-instruct | n/a | 1024 | ~60 | 2 |
| Fundamental | gemini-2.5-flash | effort: low | 1024 | ~60 | 5 |
| Sentiment | llama-3.3-70b | n/a | 1024 | ~60 | 1 |
| Macro | gpt-5-nano | effort: low | 1024 | ~60 | 1 |
| Lead/filter | kimi-k2-0905 | n/a | 1536 | ~60 | 8 |
| Verifier | deepseek-r1-0528 | default (think) | 2048 | ~30 | 6 |
| Daily bias | gemini-2.5-flash | effort: low | 1024 | 6 | <1 |
| **Total** | | | | | **~$25** |

Budget breaker: `APICostTracker` daily cap set to $2.50 (already exists).

---

## 6. Promotion bar ("validated - ready for real money")

A variant is **promotable** when, on live paper fills with measured costs:

1. **N >= 300 closed trades** (gives ~+/-5.5% CI on win rate; detects 55% vs 50%).
2. **Expectancy > 0 after spread and slippage**, with the **lower bound of the 90% CI on
   profit factor > 1.10** (not just PF > 1).
3. **t-statistic of per-trade P&L > 2.0** (Tuna's 763-trade PF 1.05 system had t=0.55 -
   that is the bar we are explicitly clearing).
4. **Max drawdown < 10% of notional account** and < 20R.
5. **No single pair contributes > 50% of net P&L** (otherwise promote the pair-specific
   sub-variant, not the family).
6. **Shadow-arm comparison reported** (LLM filter vs raw rules) - informational, not a
   gate, but you see it before deciding.

Sample-size reality: at 3-5 trades/week per variant, 300 trades is **60-100 weeks** for a
single (variant, pair). Across 6 pairs it is **10-17 weeks** per variant. That is why the
basket and the parallel tournament are not optional for this success bar.

---

## 7. Risks and honest caveats

- **The honest expected outcome is that most variants fail.** The tournament's value is
  that it tells you *which* and *why* with numbers. If all eight fail, that is itself a
  validated result: this data/execution stack has no retail-accessible edge, and the
  next question is data (order flow) or venue (spread), not indicators.
- **Paper fills flatter.** MT5 demo fills are better than live. The reconciler measures
  demo slippage; expect live to be worse. Promotion -> micro-lot live is the real test.
- **Multiple-comparison bias.** 48 cells means some will look good by chance. The
  per-variant t-stat and CI bounds in section 6 are the defence; do not relax them because
  one cell looks exciting at week 6.
- **Regime dependence.** 10-17 weeks may be one regime. A promoted trend variant that
  was validated in a trending quarter needs the ranging-quarter test too. Section 7.4's
  confirmation period is the minimum, not the ideal.
- **Research limitations this session.** Web search quota was exhausted; MQL5 signals,
  the Tuna article, and the OpenRouter catalog were fetched directly and are current as of
  2026-10-21. Academic citations are from the established literature (not re-fetched
  today); Quantpedia pages are paywalled. I would re-verify the model picks against the
  live catalog at implementation time since it changes weekly.

---

## 8. Decisions - RESOLVED (2026-10-21)

1. **XAUUSD: IN** for `TF-D1-DON20` and `TF-H4-DON20` only, excluded from SB-*/ND-*/MR-*,
   segregated reporting, own -$40 kill cap. Rationale: gold trends (the one family where
   it is an asset, not a liability) but its ATR regime and driver set are too different
   to mix into FX statistics.
2. **8-variant list: APPROVED** as written.
3. **$5 fixed risk/trade: APPROVED.**
4. **Kill thresholds: APPROVED** (-8R instant / 30-trade negative expectancy / 60-trade
   PF < 1.15).
5. **Promotion bar: APPROVED** (>=300 trades, PF 90% CI lower bound > 1.10, t-stat > 2,
   DD < 10%, no pair > 50% of P&L).
6. **Phase 7.0 runs first and alone: APPROVED**, with the refinement that
   `phase6_active` stays true through 7.0/7.1 as a free read-only validation mode and
   flips false only at Phase 7.3 tournament start.

Execution order: `pre-flight-check` -> Phase 7.0 -> `phase-closeout` -> Phase 7.1.
