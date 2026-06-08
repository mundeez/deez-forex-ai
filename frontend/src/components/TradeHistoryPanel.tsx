"use client";

import { useEffect, useState } from "react";
import { History, TrendingUp, TrendingDown, Calendar, Eye } from "lucide-react";
import { API_URL } from "@/utils/api";
import { formatDateTime } from "@/utils/date";
import { Trade } from "@/types";
import TradeDetailModal from "./TradeDetailModal";

export default function TradeHistoryPanel({ limit = 10 }: { limit?: number }) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);

  useEffect(() => {
    fetchHistory();
    const interval = setInterval(fetchHistory, 15000);
    return () => clearInterval(interval);
  }, []);

  async function fetchHistory() {
    try {
      const res = await fetch(`${API_URL}/api/v1/trades?status=closed&limit=${limit}`);
      if (!res.ok) return;
      const data = await res.json();
      setTrades(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error("history fetch error", e);
    }
  }

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
        {trades.map((t) => (
          <div
            key={t.id}
            onClick={() => setSelectedTrade(t)}
            className="flex items-center justify-between bg-slate-800/40 rounded p-2 text-sm cursor-pointer hover:bg-slate-800/70 transition group"
          >
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
              <span className="text-[10px] text-slate-500 flex items-center gap-0.5">
                <Calendar className="w-3 h-3" />
                {formatDateTime(t.close_time)}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <div className={`font-mono font-semibold ${t.pnl && t.pnl >= 0 ? "text-forex-bullish" : "text-forex-bearish"}`}>
                {t.pnl && t.pnl >= 0 ? "+" : ""}
                {t.pnl?.toFixed(2)} ({t.pnl_pct?.toFixed(2)}%)
              </div>
              <Eye className="w-3 h-3 text-slate-500 opacity-0 group-hover:opacity-100 transition" />
            </div>
          </div>
        ))}
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
