"use client";

import { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, Wallet, BarChart3, Target, Activity, TrendingUpIcon } from "lucide-react";
import { API_URL } from "@/utils/api";

interface EquityPoint {
  date: string;
  equity: number;
}

export default function ProfitMetricsPanel() {
  const [stats, setStats] = useState<any>(null);
  const [equityHistory, setEquityHistory] = useState<EquityPoint[]>([]);

  useEffect(() => {
    fetchStats();
    fetchEquityHistory();
    const interval = setInterval(() => {
      fetchStats();
    }, 15000);
    return () => clearInterval(interval);
  }, []);

  async function fetchStats() {
    try {
      const res = await fetch(`${API_URL}/api/v1/trades/stats`);
      if (!res.ok) return;
      const data = await res.json();
      setStats(data);
    } catch (e) {
      console.error("stats fetch error", e);
    }
  }

  async function fetchEquityHistory() {
    try {
      const res = await fetch(`${API_URL}/api/v1/portfolio/summary`);
      if (!res.ok) return;
      const data = await res.json();
      // In a real app, you'd fetch historical equity from a dedicated endpoint
      // For now, we'll generate a simple sparkline from available data
    } catch (e) {
      console.error("equity history fetch error", e);
    }
  }

  // Generate sparkline points from stats if available
  const sparklinePoints = stats?.equity_history || [];
  const sparklineMax = sparklinePoints.length > 0 ? Math.max(...sparklinePoints.map((p: any) => p.equity)) : 0;
  const sparklineMin = sparklinePoints.length > 0 ? Math.min(...sparklinePoints.map((p: any) => p.equity)) : 0;
  const sparklineRange = sparklineMax - sparklineMin || 1;

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="flex items-center gap-2 mb-4">
        <BarChart3 className="w-5 h-5 text-forex-accent" />
        <h2 className="text-lg font-semibold">Portfolio</h2>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="bg-slate-800/50 p-3 rounded-lg">
          <p className="text-xs text-slate-400">Equity</p>
          <p className="text-xl font-bold">${stats?.equity?.toFixed(2) || "0.00"}</p>
        </div>
        <div className="bg-slate-800/50 p-3 rounded-lg">
          <p className="text-xs text-slate-400">Daily P&L</p>
          <p className={`text-xl font-bold ${(stats?.daily_pnl || 0) >= 0 ? "text-forex-bullish" : "text-forex-bearish"}`}>
            {stats?.daily_pnl >= 0 ? "+" : ""}{stats?.daily_pnl?.toFixed(2) || "0.00"}
          </p>
        </div>
        <div className="bg-slate-800/50 p-3 rounded-lg">
          <p className="text-xs text-slate-400">Unrealized</p>
          <p className={`text-xl font-bold ${(stats?.unrealized_pnl || 0) >= 0 ? "text-forex-bullish" : "text-forex-bearish"}`}>
            {stats?.unrealized_pnl >= 0 ? "+" : ""}{stats?.unrealized_pnl?.toFixed(2) || "0.00"}
          </p>
        </div>
        <div className="bg-slate-800/50 p-3 rounded-lg">
          <p className="text-xs text-slate-400">Realized</p>
          <p className={`text-xl font-bold ${(stats?.realized_pnl || 0) >= 0 ? "text-forex-bullish" : "text-forex-bearish"}`}>
            {stats?.realized_pnl >= 0 ? "+" : ""}{stats?.realized_pnl?.toFixed(2) || "0.00"}
          </p>
        </div>
      </div>

      {/* Equity Sparkline */}
      {sparklinePoints.length > 0 && (
        <div className="mb-4">
          <p className="text-xs text-slate-400 mb-1">Equity Curve</p>
          <svg viewBox="0 0 200 40" className="w-full h-10" preserveAspectRatio="none">
            <polyline
              fill="none"
              stroke="#3b82f6"
              strokeWidth="1.5"
              points={sparklinePoints.map((p: any, i: number) => {
                const x = (i / (sparklinePoints.length - 1)) * 200;
                const y = 40 - ((p.equity - sparklineMin) / sparklineRange) * 40;
                return `${x},${y}`;
              }).join(" ")}
            />
          </svg>
        </div>
      )}

      <div className="grid grid-cols-3 gap-3 text-sm">
        <div className="bg-slate-800/30 p-2 rounded text-center">
          <p className="text-xs text-slate-400">Win Rate</p>
          <p className="font-semibold">{stats?.win_rate ? `${stats.win_rate}%` : "-"}</p>
        </div>
        <div className="bg-slate-800/30 p-2 rounded text-center">
          <p className="text-xs text-slate-400">Profit Factor</p>
          <p className="font-semibold">{stats?.profit_factor?.toFixed(2) || "-"}</p>
        </div>
        <div className="bg-slate-800/30 p-2 rounded text-center">
          <p className="text-xs text-slate-400">Trades</p>
          <p className="font-semibold">{stats?.total_trades || 0}</p>
        </div>
      </div>

      {stats && (
        <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
          <div className="bg-slate-800/30 p-2 rounded text-center">
            <p className="text-xs text-slate-400">Max Drawdown</p>
            <p className="font-semibold text-forex-bearish">{stats?.max_drawdown_pct?.toFixed(2) || "-"}%</p>
          </div>
          <div className="bg-slate-800/30 p-2 rounded text-center">
            <p className="text-xs text-slate-400">Sharpe Ratio</p>
            <p className="font-semibold">{stats?.sharpe_ratio?.toFixed(2) || "-"}</p>
          </div>
          <div className="bg-slate-800/30 p-2 rounded text-center">
            <p className="text-xs text-slate-400">Expectancy</p>
            <p className="font-semibold">{stats?.expectancy?.toFixed(2) || "-"}</p>
          </div>
          <div className="bg-slate-800/30 p-2 rounded text-center">
            <p className="text-xs text-slate-400">W/L Ratio</p>
            <p className="font-semibold">
              {stats?.winning_trades || 0}/{stats?.losing_trades || 0}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
