"use client";

import { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, Wallet, BarChart3, Target, Activity, RotateCcw, AlertTriangle, Eye } from "lucide-react";
import { API_URL } from "@/utils/api";
import { formatDateTime } from "@/utils/date";
import PortfolioIndicatorModal from "./PortfolioIndicatorModal";

interface EquityPoint {
  date: string;
  equity: number;
}

export default function ProfitMetricsPanel() {
  const [stats, setStats] = useState<any>(null);
  const [equityHistory, setEquityHistory] = useState<EquityPoint[]>([]);
  const [showConfirm, setShowConfirm] = useState(false);
  const [resetLoading, setResetLoading] = useState(false);
  const [showDetail, setShowDetail] = useState(false);

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

  async function handleReset() {
    setResetLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/portfolio/reset`, { method: "POST" });
      if (res.ok) {
        await fetchStats();
        await fetchEquityHistory();
      }
    } catch (e) {
      console.error("portfolio reset error", e);
    } finally {
      setResetLoading(false);
      setShowConfirm(false);
    }
  }

  // Generate sparkline points from stats if available
  const sparklinePoints = stats?.equity_history || [];
  const sparklineMax = sparklinePoints.length > 0 ? Math.max(...sparklinePoints.map((p: any) => p.equity)) : 0;
  const sparklineMin = sparklinePoints.length > 0 ? Math.min(...sparklinePoints.map((p: any) => p.equity)) : 0;
  const sparklineRange = sparklineMax - sparklineMin || 1;

  const hasReset = !!stats?.portfolio_reset_at;

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-forex-accent" />
          <h2 className="text-lg font-semibold">Portfolio</h2>
        </div>
        <button
          onClick={() => setShowConfirm(true)}
          className="text-xs flex items-center gap-1 px-2 py-1 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 transition"
          title="Reset portfolio statistics"
        >
          <RotateCcw className="w-3 h-3" />
          Reset
        </button>
      </div>

      {hasReset && (
        <div className="mb-3 text-[10px] text-slate-400 bg-slate-800/40 rounded px-2 py-1 flex items-center gap-1">
          <Activity className="w-3 h-3 text-forex-accent" />
          Tracking since {formatDateTime(stats.portfolio_reset_at)}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="bg-slate-800/50 p-3 rounded-lg cursor-pointer hover:bg-slate-800/70 transition group" onClick={() => setShowDetail(true)}>
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400">Equity</p>
            <Eye className="w-3 h-3 text-slate-500 opacity-0 group-hover:opacity-100 transition" />
          </div>
          <p className="text-xl font-bold">${stats?.equity?.toFixed(2) || "0.00"}</p>
        </div>
        <div className="bg-slate-800/50 p-3 rounded-lg cursor-pointer hover:bg-slate-800/70 transition group" onClick={() => setShowDetail(true)}>
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400">Daily P&L</p>
            <Eye className="w-3 h-3 text-slate-500 opacity-0 group-hover:opacity-100 transition" />
          </div>
          <p className={`text-xl font-bold ${(stats?.daily_pnl || 0) >= 0 ? "text-forex-bullish" : "text-forex-bearish"}`}>
            {stats?.daily_pnl >= 0 ? "+" : ""}{stats?.daily_pnl?.toFixed(2) || "0.00"}
          </p>
        </div>
        <div className="bg-slate-800/50 p-3 rounded-lg cursor-pointer hover:bg-slate-800/70 transition group" onClick={() => setShowDetail(true)}>
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400">Unrealized</p>
            <Eye className="w-3 h-3 text-slate-500 opacity-0 group-hover:opacity-100 transition" />
          </div>
          <p className={`text-xl font-bold ${(stats?.unrealized_pnl || 0) >= 0 ? "text-forex-bullish" : "text-forex-bearish"}`}>
            {stats?.unrealized_pnl >= 0 ? "+" : ""}{stats?.unrealized_pnl?.toFixed(2) || "0.00"}
          </p>
        </div>
        <div className="bg-slate-800/50 p-3 rounded-lg cursor-pointer hover:bg-slate-800/70 transition group" onClick={() => setShowDetail(true)}>
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400">Realized</p>
            <Eye className="w-3 h-3 text-slate-500 opacity-0 group-hover:opacity-100 transition" />
          </div>
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

      {/* Portfolio Detail Modal */}
      {showDetail && <PortfolioIndicatorModal onClose={() => setShowDetail(false)} />}

      {/* Reset Confirmation Modal */}
      {showConfirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setShowConfirm(false)}
        >
          <div
            className="bg-forex-card border border-slate-700 rounded-xl w-full max-w-sm mx-4 p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 mb-3 text-amber-400">
              <AlertTriangle className="w-5 h-5" />
              <h3 className="font-semibold text-lg">Reset Portfolio?</h3>
            </div>
            <p className="text-sm text-slate-300 mb-4">
              This will reset all portfolio statistics. Only trades closed after the reset will count toward win rate, profit factor, and equity calculations.
            </p>
            <p className="text-xs text-slate-400 mb-4">
              This action cannot be undone.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setShowConfirm(false)}
                className="px-3 py-1.5 rounded text-sm text-slate-300 hover:bg-slate-700 transition"
              >
                Cancel
              </button>
              <button
                onClick={handleReset}
                disabled={resetLoading}
                className="px-3 py-1.5 rounded text-sm bg-amber-900/50 text-amber-300 border border-amber-800 hover:bg-amber-900/70 transition disabled:opacity-50"
              >
                {resetLoading ? "Resetting..." : "Confirm Reset"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
