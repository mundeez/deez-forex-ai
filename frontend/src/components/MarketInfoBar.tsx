"use client";

import { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, Clock, Globe } from "lucide-react";
import { API_URL } from "@/utils/api";

interface MarketInfoBarProps {
  symbol: string;
  livePrice?: { bid: number; ask: number; timestamp?: string };
}

const SESSIONS = [
  { name: "Sydney", start: 22, end: 7, color: "text-emerald-400" },
  { name: "Tokyo", start: 0, end: 9, color: "text-yellow-400" },
  { name: "London", start: 8, end: 16, color: "text-blue-400" },
  { name: "New York", start: 13, end: 21, color: "text-orange-400" },
];

export default function MarketInfoBar({ symbol, livePrice }: MarketInfoBarProps) {
  const [summary, setSummary] = useState<any>(null);
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    fetchSummary();
    const interval = setInterval(() => {
      fetchSummary();
      setNow(new Date());
    }, 10000);
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

  const currentHour = now.getUTCHours();
  const activeSessions = SESSIONS.filter((s) => {
    if (s.start > s.end) {
      return currentHour >= s.start || currentHour < s.end;
    }
    return currentHour >= s.start && currentHour < s.end;
  });

  const bid = livePrice?.bid ?? summary?.bid;
  const ask = livePrice?.ask ?? summary?.ask;
  const spread = bid && ask ? ask - bid : summary?.spread;

  const changeColor = summary?.day_change_pct && summary.day_change_pct >= 0 ? "text-forex-bullish" : "text-forex-bearish";
  const ChangeIcon = summary?.day_change_pct && summary.day_change_pct >= 0 ? TrendingUp : TrendingDown;

  // Daily range percentage
  const dayRange = summary?.day_high && summary?.day_low ? summary.day_high - summary.day_low : 0;
  const currentInRange = summary?.day_high && summary?.day_low && bid ? ((bid - summary.day_low) / dayRange) * 100 : null;

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">{symbol}</h2>
        <div className="flex items-center gap-2 text-xs">
          <Globe className="w-3 h-3 text-slate-400" />
          {SESSIONS.map((s) => {
            const isActive = activeSessions.some((a) => a.name === s.name);
            return (
              <span key={s.name} className={`px-1.5 py-0.5 rounded border ${isActive ? "border-slate-500 bg-slate-800" : "border-transparent text-slate-600"} ${isActive ? s.color : ""}`}>
                {s.name}
              </span>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
        <div>
          <p className="text-xs text-slate-400">Bid</p>
          <p className="text-xl font-bold text-forex-bullish">{bid?.toFixed(5) || "-"}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">Ask</p>
          <p className="text-xl font-bold text-forex-bearish">{ask?.toFixed(5) || "-"}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">Spread</p>
          <p className="text-xl font-bold">{spread ? spread.toFixed(5) : "-"}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">Day Range</p>
          <p className="text-sm font-mono">{summary?.day_low?.toFixed(5) || "-"} - {summary?.day_high?.toFixed(5) || "-"}</p>
          {currentInRange !== null && (
            <div className="mt-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div className="h-full bg-forex-accent" style={{ width: `${Math.max(0, Math.min(100, currentInRange))}%` }} />
            </div>
          )}
        </div>
        <div>
          <p className="text-xs text-slate-400">Change</p>
          <div className={`flex items-center gap-1 ${changeColor}`}>
            <ChangeIcon className="w-4 h-4" />
            <p className="text-sm font-semibold">{summary?.day_change_pct?.toFixed(4) || "-"}%</p>
          </div>
        </div>
        <div>
          <p className="text-xs text-slate-400">Session</p>
          <div className="flex items-center gap-1 text-xs text-slate-300">
            <Clock className="w-3 h-3" />
            <span>{activeSessions.map((s) => s.name).join(", ") || "Closed"}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
