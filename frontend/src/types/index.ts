/**
 * Shared TypeScript types for deez-forex-ai frontend.
 * Replaces widespread `any` usage with strongly-typed interfaces.
 */

export interface PriceTick {
  symbol: string;
  bid: number;
  ask: number;
  timestamp: number | string;
}

export interface Trade {
  id: number;
  symbol: string;
  direction: "buy" | "sell";
  status: "open" | "closed";
  mode: "paper" | "live";
  strategy_mode?: string | null;
  entry_price: number;
  exit_price?: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  position_size: number;
  original_position_size?: number | null;
  risk_pct: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  partial_pnl?: number | null;
  closed_portion?: number | null;
  open_time: string;
  close_time: string | null;
  close_reason: string | null;
  ai_decision_id: number | null;
  rationale: string | null;
  provider?: string | null;
  trailing_stop_active?: boolean | null;
  trailing_stop_distance?: number | null;
  highest_price_seen?: number | null;
  lowest_price_seen?: number | null;
  duration_minutes?: number;
  distance_to_sl?: number | null;
  distance_to_tp?: number | null;
  session_at_open?: string | null;
  session_at_close?: string | null;
  actual_holding_min?: number | null;
  mfe_pips?: number | null;
  mae_pips?: number | null;
  peak_pnl?: number | null;
  peak_pnl_time?: string | null;
  max_risk_amount?: number | null;
  partial_tp_hit?: boolean | null;
  partial_profit_pnl?: number | null;
  created_at?: string;
  meta_order_id?: string | null;
}

export interface AIDecision {
  id: number;
  symbol: string;
  decision: "BUY" | "SELL" | "HOLD";
  confidence: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  timeframe: string;
  rationale: string;
  timestamp: string;
}

export interface PortfolioSummary {
  equity: number;
  daily_pnl: number;
  unrealized_pnl: number;
  realized_pnl: number;
  win_rate: number | null;
  profit_factor: number | null;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  total_trades: number;
  open_trades: number;
  equity_curve: { timestamp: string; equity: number }[];
}

export interface MarketSummary {
  symbol: string;
  bid: number;
  ask: number;
  spread: number | null;
  day_high: number | null;
  day_low: number | null;
  day_change_pct: number | null;
  session_status: string;
}

export interface AnalysisResult {
  symbol: string;
  technical_signal: string;
  fundamental_signal: string;
  sentiment_signal: string;
  combined_signal: string;
  ai_decision: string | null;
  ai_confidence: number | null;
}

export interface AppSettings {
  default_pair: string;
  data_provider: string;
  strategy_mode: string;
  max_risk_per_trade_pct: number;
  max_risk_per_trade_abs: number | null;
  max_daily_loss_pct: number;
  ai_confidence_threshold: number;
  min_risk_reward: number;
  default_mode: string;
  manual_override: boolean;
  max_open_per_symbol: number;
  equity_balance: number;
  max_trade_duration_min: number;
  eod_close_enabled: boolean;
  eod_close_time_utc: string;
  eod_no_new_entries_before: string;
  weekend_close_enabled: boolean;
  weekend_close_time_utc: string;
  weekend_resume_time_utc: string;
  enable_technical: boolean;
  enable_fundamental: boolean;
  enable_sentiment: boolean;
  chart_refresh_ms: number;
  analysis_poll_ms: number;
  trailing_stop_enabled: boolean;
  trailing_stop_distance_atr: number;
  partial_profit_enabled: boolean;
  partial_profit_pct: number;
  spread_filter_enabled: boolean;
  max_spread_to_atr_ratio: number;
  drawdown_guard_enabled: boolean;
  correlation_guard_enabled: boolean;
  batched_ai_enabled: boolean;
  auto_strategy_switch_enabled: boolean;
  news_halt_enabled: boolean;
  news_halt_buffer_before_min: number;
  news_halt_buffer_after_min: number;
  active_pairs: ActivePair[];
  webhook_url: string;
  discord_webhook_url: string;
  slack_webhook_url: string;
  pushover_app_token: string;
  pushover_user_key: string;
}

export interface ActivePair {
  id: number;
  symbol: string;
  selection_mode: string;
  priority: number;
}

export interface Suggestion {
  symbol: string;
  profitability_score: number;
  volatility_score: number;
  trend_strength: number;
  recommendation: string;
}

export type WebSocketMessage =
  | { type: "price_tick"; topic: "prices"; symbol: string; bid: number; ask: number; timestamp: string }
  | { type: "trade_event"; topic: "trades"; event: string; data: Trade }
  | { type: "ai_decision"; topic: "ai_decisions"; data: AIDecision }
  | { type: "settings_change"; topic: "settings"; [key: string]: any }
  | { type: "pong" }
  | { type: "subscription_updated"; topics: string[] }
  | { type: "echo"; data: any };
