"use client";

import { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, Clock } from "lucide-react";
import { API_URL } from "@/utils/api";

interface MarketInfoBarProps {
  symbol: string;
}

export default function MarketInfoBar({ symbol }: MarketInfoBarProps) {
  const [summary, setSummary] = useState<any>(null);

  useEffect(() => {
    fetchSummary();
    const interval = setInterval(fetchSummary, 10000);
    return () => clearInterval(interval);
  }, [symbol]);

  async function fetchSummary() {
    try {
      const res = await fetch(`${API_URL}/api/v1/market/summary?symbol=${symbol}`);
      if (!res.ok) return;
      const data = await res.json();
      setSummary(data);
    } catch (e) {
      console.error("market summary error", e);
    }
  }

  const spread = summary?.spread ? summary.spread.toFixed(5) : "-";
  const changeColor = summary?.day_change_pct && summary.day_change_pct >= 0 ? "text-forex-bullish" : "text-forex-bearish";
  const ChangeIcon = summary?.day_change_pct && summary.day_change_pct >= 0 ? TrendingUp : TrendingDown;

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">{symbol}</h2>
        <div className="flex items-center gap-1 text-xs text-slate-400">
          <Clock className="w-3 h-3" />
          <span>{summary?.session_status || "Loading..."}</span>
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div>
          <p className="text-xs text-slate-400">Bid</p>
          <p className="text-xl font-bold text-forex-bullish">{summary?.bid?.toFixed(5) || "-"}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">Ask</p>
          <p className="text-xl font-bold text-forex-bearish">{summary?.ask?.toFixed(5) || "-"}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">Spread</p>
          <p className="text-xl font-bold">{spread}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">Day Range</p>
          <p className="text-sm font-mono">{summary?.day_low?.toFixed(5) || "-"} - {summary?.day_high?.toFixed(5) || "-"}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">Change</p>
          <div className={`flex items-center gap-1 ${changeColor}`}>
            <ChangeIcon className="w-4 h-4" />
            <p className="text-sm font-semibold">{summary?.day_change_pct?.toFixed(4) || "-"}%</p>
          </div>
        </div>
      </div>
    </div>
  );
}
