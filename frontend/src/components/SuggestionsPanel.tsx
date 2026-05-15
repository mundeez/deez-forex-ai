"use client";

import { useEffect, useState } from "react";
import { Lightbulb, TrendingUp, Clock, Calendar, BarChart3 } from "lucide-react";
import { API_URL } from "@/utils/api";

interface Suggestion {
  symbol: string;
  profitability_score: number;
  win_rate_24h: number;
  avg_pnl_recent: number;
  total_trades_recent: number;
  recommendation: string;
}

interface HourlySuggestion {
  hour_utc: number;
  best_pair: string;
  score: number;
  recommendation: string;
}

export default function SuggestionsPanel() {
  const [bestNow, setBestNow] = useState<Suggestion[]>([]);
  const [todayTimeline, setTodayTimeline] = useState<HourlySuggestion[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchBestNow();
    fetchToday();
    const interval = setInterval(() => {
      fetchBestNow();
      fetchToday();
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  async function fetchBestNow() {
    try {
      const res = await fetch(`${API_URL}/api/v1/suggestions/best-now`);
      if (!res.ok) return;
      const data = await res.json();
      setBestNow(data.suggestions || []);
    } catch (e) {
      console.error("best-now fetch error", e);
    } finally {
      setLoading(false);
    }
  }

  async function fetchToday() {
    try {
      const res = await fetch(`${API_URL}/api/v1/suggestions/today`);
      if (!res.ok) return;
      const data = await res.json();
      setTodayTimeline(data.timeline || []);
    } catch (e) {
      console.error("today fetch error", e);
    }
  }

  function formatHour(h: number) {
    return `${h.toString().padStart(2, "0")}:00 UTC`;
  }

  function recommendationColor(rec: string) {
    switch (rec) {
      case "strong_buy": return "text-emerald-400";
      case "favorable": return "text-emerald-300";
      case "neutral": return "text-slate-400";
      case "unfavorable": return "text-amber-400";
      case "avoid": return "text-red-400";
      default: return "text-slate-400";
    }
  }

  function recommendationBg(rec: string) {
    switch (rec) {
      case "strong_buy": return "bg-emerald-900/30 border-emerald-700";
      case "favorable": return "bg-emerald-900/20 border-emerald-800";
      case "neutral": return "bg-slate-800/50 border-slate-700";
      case "unfavorable": return "bg-amber-900/20 border-amber-800";
      case "avoid": return "bg-red-900/20 border-red-800";
      default: return "bg-slate-800/50 border-slate-700";
    }
  }

  const nowHour = new Date().getUTCHours();

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="flex items-center gap-2 mb-3">
        <Lightbulb className="w-5 h-5 text-amber-400" />
        <h2 className="text-lg font-semibold">AI Suggestions</h2>
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Loading suggestions...</p>
      ) : (
        <div className="space-y-4">
          {/* Best Now */}
          <div>
            <h3 className="text-sm font-semibold text-slate-300 mb-2 flex items-center gap-1">
              <TrendingUp className="w-4 h-4 text-forex-accent" /> Best Opportunities Right Now
            </h3>
            {bestNow.length === 0 ? (
              <p className="text-xs text-slate-500">No suggestion data yet. Run some trades to build statistics.</p>
            ) : (
              <div className="space-y-2">
                {bestNow.map((s, idx) => (
                  <div key={idx} className={`p-3 rounded-lg border text-sm ${recommendationBg(s.recommendation)}`}>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white">{s.symbol}</span>
                        <span className={`text-xs font-semibold uppercase ${recommendationColor(s.recommendation)}`}>
                          {s.recommendation.replace("_", " ")}
                        </span>
                      </div>
                      <div className="text-right">
                        <span className="text-xs text-slate-400">Score</span>
                        <p className="font-bold text-white">{s.profitability_score}/100</p>
                      </div>
                    </div>
                    <div className="grid grid-cols-3 gap-2 mt-2 text-xs text-slate-400">
                      <span>Win Rate: {s.win_rate_24h}%</span>
                      <span>Avg PnL: ${s.avg_pnl_recent.toFixed(2)}</span>
                      <span>Trades: {s.total_trades_recent}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Today's Timeline */}
          <div>
            <h3 className="text-sm font-semibold text-slate-300 mb-2 flex items-center gap-1">
              <Clock className="w-4 h-4 text-forex-accent" /> Today&apos;s Timeline
            </h3>
            <div className="space-y-1 max-h-48 overflow-auto">
              {todayTimeline.slice(0, 12).map((h, idx) => {
                const isNow = h.hour_utc === nowHour;
                return (
                  <div
                    key={idx}
                    className={`flex items-center justify-between p-2 rounded text-xs ${
                      isNow ? "bg-forex-accent/20 border border-forex-accent/40" : "bg-slate-800/30"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className={`w-1.5 h-1.5 rounded-full ${
                        h.score >= 70 ? "bg-emerald-400" : h.score >= 40 ? "bg-amber-400" : "bg-red-400"
                      }`} />
                      <span className={isNow ? "text-white font-semibold" : "text-slate-400"}>
                        {formatHour(h.hour_utc)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-slate-300">{h.best_pair || "-"}</span>
                      <span className="text-slate-500">{h.score.toFixed(0)}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
