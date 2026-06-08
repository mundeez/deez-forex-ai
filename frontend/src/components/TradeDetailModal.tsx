"use client";

import { X, TrendingUp, TrendingDown, Calendar, Clock, Target, Shield, Timer, Activity, Maximize2, MessageSquare, Tag } from "lucide-react";
import { Trade } from "@/types";
import { formatDateTime } from "@/utils/date";

interface TradeDetailModalProps {
  trade: Trade | null;
  onClose: () => void;
}

function formatNumber(n: number | null | undefined, digits = 2): string {
  if (n == null) return "—";
  return n.toFixed(digits);
}

function formatDuration(minutes?: number | null): string {
  if (!minutes) return "—";
  const h = Math.floor(minutes / 60);
  const m = Math.floor(minutes % 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function getSessionBadge(session?: string | null): string {
  if (!session) return "";
  const map: Record<string, string> = {
    asian: "Asian",
    london: "London",
    ny: "New York",
    london_ny_overlap: "London/NY Overlap",
  };
  return map[session] || session;
}

function getCloseReasonBadge(reason?: string | null): { text: string; color: string } {
  if (!reason) return { text: "—", color: "bg-slate-700 text-slate-300" };
  const map: Record<string, string> = {
    tp_hit: "bg-emerald-900/50 text-emerald-300",
    sl_hit: "bg-red-900/50 text-red-300",
    time_based: "bg-amber-900/50 text-amber-300",
    eod_close: "bg-blue-900/50 text-blue-300",
    weekend_close: "bg-purple-900/50 text-purple-300",
    manual: "bg-slate-700 text-slate-300",
    trailing_stop: "bg-cyan-900/50 text-cyan-300",
    partial_tp: "bg-emerald-900/50 text-emerald-300",
  };
  return {
    text: reason.replace(/_/g, " ").toUpperCase(),
    color: map[reason] || "bg-slate-700 text-slate-300",
  };
}

export default function TradeDetailModal({ trade, onClose }: TradeDetailModalProps) {
  if (!trade) return null;

  const closeBadge = getCloseReasonBadge(trade.close_reason);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-forex-card border border-slate-700 rounded-xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-700">
          <div className="flex items-center gap-2">
            {trade.direction === "buy" ? (
              <TrendingUp className="w-5 h-5 text-forex-bullish" />
            ) : (
              <TrendingDown className="w-5 h-5 text-forex-bearish" />
            )}
            <h2 className="text-lg font-semibold">
              {trade.symbol} {trade.direction.toUpperCase()}
            </h2>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded ${
                trade.mode === "live"
                  ? "bg-red-900/50 text-red-300"
                  : "bg-blue-900/50 text-blue-300"
              }`}
            >
              {trade.mode.toUpperCase()}
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">
              {trade.status.toUpperCase()}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* PnL Banner */}
        <div className="p-4 border-b border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-slate-400">Profit / Loss</p>
              <p
                className={`text-2xl font-bold ${
                  (trade.pnl || 0) >= 0 ? "text-forex-bullish" : "text-forex-bearish"
                }`}
              >
                {trade.pnl && trade.pnl >= 0 ? "+" : ""}${formatNumber(trade.pnl)}
              </p>
              <p className="text-sm text-slate-400">
                {trade.pnl_pct && trade.pnl_pct >= 0 ? "+" : ""}
                {formatNumber(trade.pnl_pct)}%
              </p>
            </div>
            <div className="text-right space-y-1">
              {trade.close_reason && (
                <span className={`text-[10px] px-2 py-1 rounded ${closeBadge.color}`}>
                  {closeBadge.text}
                </span>
              )}
              {trade.partial_tp_hit && (
                <span className="ml-2 text-[10px] px-2 py-1 rounded bg-emerald-900/50 text-emerald-300">
                  PARTIAL TP
                </span>
              )}
              {trade.session_at_open && (
                <div className="text-[10px] text-slate-400">
                  {getSessionBadge(trade.session_at_open)}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Details Grid */}
        <div className="p-4 grid grid-cols-2 gap-4 text-sm border-b border-slate-700">
          <DetailItem label="Entry Price" value={formatNumber(trade.entry_price, 5)} />
          <DetailItem label="Exit Price" value={formatNumber(trade.exit_price, 5)} />
          <DetailItem label="Stop Loss" value={formatNumber(trade.stop_loss, 5)} icon={<Shield className="w-3 h-3 text-red-400" />} />
          <DetailItem label="Take Profit" value={formatNumber(trade.take_profit, 5)} icon={<Target className="w-3 h-3 text-emerald-400" />} />
          <DetailItem label="Position Size" value={formatNumber(trade.position_size, 4)} />
          <DetailItem label="Original Size" value={formatNumber(trade.original_position_size, 4)} />
          <DetailItem label="Risk %" value={`${formatNumber(trade.risk_pct)}%`} />
          <DetailItem label="Max Risk Amount" value={`$${formatNumber(trade.max_risk_amount)}`} />
        </div>

        {/* Timing */}
        <div className="p-4 border-b border-slate-700 space-y-2 text-sm">
          <div className="flex items-center gap-2 text-slate-400">
            <Calendar className="w-4 h-4" />
            <span className="text-xs uppercase tracking-wider">Timing</span>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs text-slate-500">Opened</p>
              <p className="text-slate-200">{formatDateTime(trade.open_time)}</p>
            </div>
            {trade.close_time && (
              <div>
                <p className="text-xs text-slate-500">Closed</p>
                <p className="text-slate-200">{formatDateTime(trade.close_time)}</p>
              </div>
            )}
            <div>
              <p className="text-xs text-slate-500">Duration</p>
              <p className="text-slate-200 flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {formatDuration(trade.actual_holding_min ?? trade.duration_minutes)}
              </p>
            </div>
            {trade.strategy_mode && (
              <div>
                <p className="text-xs text-slate-500">Strategy</p>
                <p className="text-slate-200 capitalize">{trade.strategy_mode.replace(/_/g, " ")}</p>
              </div>
            )}
          </div>
        </div>

        {/* Performance Metrics */}
        {(trade.mfe_pips != null || trade.mae_pips != null || trade.peak_pnl != null) && (
          <div className="p-4 border-b border-slate-700 space-y-2 text-sm">
            <div className="flex items-center gap-2 text-slate-400">
              <Maximize2 className="w-4 h-4" />
              <span className="text-xs uppercase tracking-wider">Performance Extremes</span>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <DetailItem label="MFE (pips)" value={formatNumber(trade.mfe_pips, 1)} />
              <DetailItem label="MAE (pips)" value={formatNumber(trade.mae_pips, 1)} />
              <DetailItem label="Peak PnL" value={`$${formatNumber(trade.peak_pnl)}`} />
              <DetailItem label="Peak PnL Time" value={formatDateTime(trade.peak_pnl_time)} />
              <DetailItem label="Highest Price" value={formatNumber(trade.highest_price_seen, 5)} />
              <DetailItem label="Lowest Price" value={formatNumber(trade.lowest_price_seen, 5)} />
            </div>
          </div>
        )}

        {/* Partial Close */}
        {(trade.partial_pnl != null || trade.closed_portion != null) && (
          <div className="p-4 border-b border-slate-700 space-y-2 text-sm">
            <div className="flex items-center gap-2 text-slate-400">
              <Activity className="w-4 h-4" />
              <span className="text-xs uppercase tracking-wider">Partial Close</span>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <DetailItem label="Closed Portion" value={`${formatNumber((trade.closed_portion || 0) * 100, 1)}%`} />
              <DetailItem label="Partial PnL" value={`$${formatNumber(trade.partial_pnl)}`} />
              <DetailItem label="Partial Profit PnL" value={`$${formatNumber(trade.partial_profit_pnl)}`} />
            </div>
          </div>
        )}

        {/* Trailing Stop */}
        {trade.trailing_stop_active && (
          <div className="p-4 border-b border-slate-700 space-y-2 text-sm">
            <div className="flex items-center gap-2 text-slate-400">
              <Timer className="w-4 h-4" />
              <span className="text-xs uppercase tracking-wider">Trailing Stop</span>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <DetailItem label="Active" value="Yes" />
              <DetailItem label="Distance" value={`${formatNumber(trade.trailing_stop_distance, 1)} pips`} />
            </div>
          </div>
        )}

        {/* Rationale */}
        {trade.rationale && (
          <div className="p-4 space-y-2 text-sm">
            <div className="flex items-center gap-2 text-slate-400">
              <MessageSquare className="w-4 h-4" />
              <span className="text-xs uppercase tracking-wider">Rationale</span>
            </div>
            <p className="text-slate-300 text-sm leading-relaxed whitespace-pre-wrap">
              {trade.rationale}
            </p>
          </div>
        )}

        {/* Meta */}
        <div className="p-4 border-t border-slate-700 text-xs text-slate-500 flex items-center gap-4">
          {trade.meta_order_id && (
            <span className="flex items-center gap-1">
              <Tag className="w-3 h-3" />
              Order: {trade.meta_order_id}
            </span>
          )}
          {trade.provider && <span>Provider: {trade.provider}</span>}
          {trade.ai_decision_id && <span>AI Decision #{trade.ai_decision_id}</span>}
          <span className="ml-auto">Trade #{trade.id}</span>
        </div>
      </div>
    </div>
  );
}

function DetailItem({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon?: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-slate-200 flex items-center gap-1">
        {icon}
        {value}
      </p>
    </div>
  );
}
