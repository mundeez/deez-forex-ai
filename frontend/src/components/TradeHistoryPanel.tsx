"use client";

import { useState } from "react";
import { History, TrendingUp, TrendingDown, Calendar, Eye } from "lucide-react";
import { API_URL } from "@/utils/api";
import { usePolling, fetchJSON } from "@/hooks/usePolling";
import { formatDateTime } from "@/utils/date";
import { formatDuration, formatNumber, computeRMultiple } from "@/utils/format";
import { classifySession, formatSession } from "@/utils/sessions";
import { Trade } from "@/types";
import TradeDetailModal from "./TradeDetailModal";

function closeReasonClass(reason?: string | null): string {
  if (!reason) return "bg-slate-700 text-slate-300";
  switch (reason.toLowerCase()) {
    case "take_profit":
      return "bg-emerald-900/50 text-emerald-300";
    case "stop_loss":
      return "bg-red-900/50 text-red-300";
    case "trailing_stop":
      return "bg-amber-900/50 text-amber-300";
    case "eod":
    case "weekend":
    case "overnight":
      return "bg-slate-700 text-slate-300";
    default:
      return "bg-blue-900/50 text-blue-300";
  }
}

export default function TradeHistoryPanel({ limit = 10 }: { limit?: number }) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);

  usePolling(async (signal) => {
    const data = await fetchJSON<Trade[]>(`${API_URL}/api/v1/trades?status=closed&limit=${limit}`, signal);
    if (data) setTrades(Array.isArray(data) ? data : []);
  }, 15000, [limit]);

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="flex items-center gap-2 mb-3">
        <History className="w-4 h-4 text-forex-accent" />
        <h2 className="text-lg font-semibold">Trade History</h2>
      </div>
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {trades.length === 0 && (
          <p className="text-sm text-slate-500">No closed trades yet.</p>
        )}
        {trades.map((t) => {
          const rMultiple = computeRMultiple(t.pnl_pct, t.entry_price, t.stop_loss, t.risk_pct);
          return (
            <div
              key={t.id}
              onClick={() => setSelectedTrade(t)}
              className="flex flex-col gap-1 bg-slate-800/40 rounded p-2 text-sm cursor-pointer hover:bg-slate-800/70 transition group"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {t.pnl && t.pnl >= 0 ? (
                    <TrendingUp className="w-3 h-3 text-forex-bullish" />
                  ) : (
                    <TrendingDown className="w-3 h-3 text-forex-bearish" />
                  )}
                  <span className="font-semibold">{t.symbol}</span>
                  <span className={`text-xs uppercase ${t.direction === "buy" ? "text-forex-bullish" : "text-forex-bearish"}`}>
                    {t.direction}
                  </span>
                  <span className="text-xs text-slate-500">{t.mode}</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className={`font-mono font-semibold ${t.pnl && t.pnl >= 0 ? "text-forex-bullish" : "text-forex-bearish"}`}>
                    {t.pnl && t.pnl >= 0 ? "+" : ""}
                    {t.pnl?.toFixed(2)} ({t.pnl_pct?.toFixed(2)}%)
                  </div>
                  <Eye className="w-3 h-3 text-slate-500 opacity-0 group-hover:opacity-100 transition" />
                </div>
              </div>
              <div className="flex items-center justify-between text-xs text-slate-400">
                <div className="flex items-center gap-2">
                  <span className="flex items-center gap-0.5">
                    <Calendar className="w-3 h-3" />
                    {formatDateTime(t.close_time)}
                  </span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">
                    {formatSession(classifySession(t.close_time))}
                  </span>
                  <span>{formatDuration(t.actual_holding_min)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span>{formatNumber(t.entry_price, 5)} → {formatNumber(t.exit_price, 5)}</span>
                  <span className="text-slate-500">R: {rMultiple !== null ? rMultiple.toFixed(2) : "—"}</span>
                </div>
              </div>
              {t.close_reason && (
                <div className="flex justify-end">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${closeReasonClass(t.close_reason)}`}>
                    {t.close_reason.replace(/_/g, " ")}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {selectedTrade && (
        <TradeDetailModal
          trade={selectedTrade}
          onClose={() => setSelectedTrade(null)}
        />
      )}
    </div>
  );
}
