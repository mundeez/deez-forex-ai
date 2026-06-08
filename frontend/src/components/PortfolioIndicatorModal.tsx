"use client";

import { useEffect, useState } from "react";
import { X, TrendingUp, TrendingDown, BarChart3, PieChart, Activity, Target, Shield, Clock, Calendar, Zap, Award, AlertTriangle } from "lucide-react";
import { API_URL } from "@/utils/api";
import { formatDateTime } from "@/utils/date";

interface PortfolioStats {
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  daily_pnl: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number | null;
  profit_factor: number | null;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  expectancy: number | null;
  portfolio_reset_at?: string | null;
}

interface DailyRecord {
  date: string;
  realized_pnl: number;
  unrealized_pnl: number;
  equity: number | null;
}

interface PortfolioIndicatorModalProps {
  onClose: () => void;
}

export default function PortfolioIndicatorModal({ onClose }: PortfolioIndicatorModalProps) {
  const [stats, setStats] = useState<PortfolioStats | null>(null);
  const [dailyHistory, setDailyHistory] = useState<DailyRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchData();
  }, []);

  async function fetchData() {
    try {
      const [statsRes, dailyRes] = await Promise.all([
        fetch(`${API_URL}/api/v1/trades/stats`),
        fetch(`${API_URL}/api/v1/portfolio/daily?days=30`),
      ]);
      if (statsRes.ok) {
        setStats(await statsRes.json());
      }
      if (dailyRes.ok) {
        const dailyData = await dailyRes.json();
        setDailyHistory(dailyData.records || []);
      }
    } catch (e) {
      console.error("portfolio detail fetch error", e);
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
        <div className="bg-forex-card border border-slate-700 rounded-xl p-8" onClick={(e) => e.stopPropagation()}>
          <div className="animate-spin w-6 h-6 border-2 border-forex-accent border-t-transparent rounded-full mx-auto" />
          <p className="text-sm text-slate-400 mt-2">Loading portfolio details...</p>
        </div>
      </div>
    );
  }

  if (!stats) return null;

  const totalClosed = stats.total_trades || 0;
  const wins = stats.winning_trades || 0;
  const losses = stats.losing_trades || 0;
  const avgWin = wins > 0 ? stats.realized_pnl / wins : 0;
  const avgLoss = losses > 0 ? (stats.realized_pnl - (stats.realized_pnl / wins) * wins) / losses : 0;
  const netPnl = stats.realized_pnl + stats.unrealized_pnl;

  // Daily history sparkline data (last 14 days max)
  const recentDays = dailyHistory.slice(0, 14).reverse();
  const hasDailyData = recentDays.length > 1;
  const dailyMin = hasDailyData ? Math.min(...recentDays.map((d) => d.equity || 0)) : 0;
  const dailyMax = hasDailyData ? Math.max(...recentDays.map((d) => d.equity || 0)) : 1;
  const dailyRange = dailyMax - dailyMin || 1;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-forex-card border border-slate-700 rounded-xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-700">
          <div className="flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-forex-accent" />
            <h2 className="text-lg font-semibold">Portfolio Details</h2>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white transition">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Equity Breakdown */}
        <div className="p-4 border-b border-slate-700">
          <div className="flex items-center gap-2 mb-3 text-slate-400">
            <Activity className="w-4 h-4" />
            <span className="text-xs uppercase tracking-wider font-medium">Equity Breakdown</span>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <MetricCard label="Equity" value={`$${stats.equity.toFixed(2)}`} accent />
            <MetricCard
              label="Realized P&L"
              value={`${stats.realized_pnl >= 0 ? "+" : ""}$${stats.realized_pnl.toFixed(2)}`}
              positive={stats.realized_pnl >= 0}
            />
            <MetricCard
              label="Unrealized P&L"
              value={`${stats.unrealized_pnl >= 0 ? "+" : ""}$${stats.unrealized_pnl.toFixed(2)}`}
              positive={stats.unrealized_pnl >= 0}
            />
          </div>
          <div className="mt-3 bg-slate-800/40 rounded p-2 text-xs text-slate-400 flex items-center gap-2">
            <Zap className="w-3 h-3 text-amber-400" />
            <span>
              Net P&L: <span className={netPnl >= 0 ? "text-forex-bullish" : "text-forex-bearish"}>
                {netPnl >= 0 ? "+" : ""}${netPnl.toFixed(2)}
              </span>
              {stats.portfolio_reset_at && (
                <span className="ml-2 text-slate-500">(since {formatDateTime(stats.portfolio_reset_at)})</span>
              )}
            </span>
          </div>
        </div>

        {/* Trade Performance */}
        <div className="p-4 border-b border-slate-700">
          <div className="flex items-center gap-2 mb-3 text-slate-400">
            <Target className="w-4 h-4" />
            <span className="text-xs uppercase tracking-wider font-medium">Trade Performance</span>
          </div>
          <div className="grid grid-cols-4 gap-3">
            <MetricCard label="Total Trades" value={String(totalClosed)} />
            <MetricCard label="Wins" value={String(wins)} positive />
            <MetricCard label="Losses" value={String(losses)} negative />
            <MetricCard label="Win Rate" value={stats.win_rate != null ? `${stats.win_rate.toFixed(1)}%` : "—"} />
          </div>
          <div className="grid grid-cols-3 gap-3 mt-3">
            <MetricCard label="Profit Factor" value={stats.profit_factor?.toFixed(2) || "—"} />
            <MetricCard label="Expectancy" value={stats.expectancy != null ? `$${stats.expectancy.toFixed(2)}` : "—"} />
            <MetricCard
              label="Avg per Trade"
              value={totalClosed > 0 ? `$${(stats.realized_pnl / totalClosed).toFixed(2)}` : "—"}
              positive={totalClosed > 0 ? stats.realized_pnl / totalClosed >= 0 : undefined}
            />
          </div>
        </div>

        {/* Risk Metrics */}
        <div className="p-4 border-b border-slate-700">
          <div className="flex items-center gap-2 mb-3 text-slate-400">
            <Shield className="w-4 h-4" />
            <span className="text-xs uppercase tracking-wider font-medium">Risk Metrics</span>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <MetricCard
              label="Max Drawdown"
              value={`${stats.max_drawdown_pct.toFixed(2)}%`}
              negative
            />
            <MetricCard label="Sharpe Ratio" value={stats.sharpe_ratio.toFixed(2)} />
            <MetricCard
              label="Daily P&L"
              value={`${stats.daily_pnl >= 0 ? "+" : ""}$${stats.daily_pnl.toFixed(2)}`}
              positive={stats.daily_pnl >= 0}
            />
          </div>
        </div>

        {/* Equity History Sparkline */}
        {hasDailyData && (
          <div className="p-4 border-b border-slate-700">
            <div className="flex items-center gap-2 mb-3 text-slate-400">
              <TrendingUp className="w-4 h-4" />
              <span className="text-xs uppercase tracking-wider font-medium">Equity History (14 Days)</span>
            </div>
            <div className="bg-slate-800/30 rounded p-3">
              <svg viewBox={`0 0 ${recentDays.length * 20} 60`} className="w-full h-16" preserveAspectRatio="none">
                {/* Grid lines */}
                {[0, 20, 40, 60].map((y) => (
                  <line key={y} x1="0" y1={y} x2={recentDays.length * 20} y2={y} stroke="#334155" strokeWidth="0.5" />
                ))}
                {/* Area under curve */}
                <polygon
                  fill="rgba(59,130,246,0.15)"
                  points={`
                    0,60
                    ${recentDays.map((d, i) => {
                      const x = i * 20 + 10;
                      const y = 60 - ((d.equity || dailyMin) - dailyMin) / dailyRange * 55 - 2.5;
                      return `${x},${y}`;
                    }).join(" ")}
                    ${(recentDays.length - 1) * 20 + 10},60
                  `}
                />
                {/* Line */}
                <polyline
                  fill="none"
                  stroke="#3b82f6"
                  strokeWidth="2"
                  points={recentDays.map((d, i) => {
                    const x = i * 20 + 10;
                    const y = 60 - ((d.equity || dailyMin) - dailyMin) / dailyRange * 55 - 2.5;
                    return `${x},${y}`;
                  }).join(" ")}
                />
                {/* Dots */}
                {recentDays.map((d, i) => {
                  const x = i * 20 + 10;
                  const y = 60 - ((d.equity || dailyMin) - dailyMin) / dailyRange * 55 - 2.5;
                  return (
                    <circle key={i} cx={x} cy={y} r="3" fill="#3b82f6" stroke="#1e293b" strokeWidth="1" />
                  );
                })}
              </svg>
              <div className="flex justify-between text-[10px] text-slate-500 mt-1">
                {recentDays.map((d, i) => (
                  <span key={i} className={i % 3 === 0 ? "" : "hidden sm:inline"}>
                    {new Date(d.date).getDate()}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Daily Records Table */}
        {dailyHistory.length > 0 && (
          <div className="p-4">
            <div className="flex items-center gap-2 mb-3 text-slate-400">
              <Calendar className="w-4 h-4" />
              <span className="text-xs uppercase tracking-wider font-medium">Daily Records</span>
            </div>
            <div className="max-h-40 overflow-y-auto space-y-1">
              {dailyHistory.slice(0, 10).map((r, i) => (
                <div key={i} className="flex items-center justify-between text-sm bg-slate-800/30 rounded px-2 py-1">
                  <span className="text-slate-400 text-xs">{formatDateTime(r.date).split(" ").slice(0, 3).join(" ")}</span>
                  <div className="flex items-center gap-3">
                    <span className={`text-xs ${r.realized_pnl >= 0 ? "text-forex-bullish" : "text-forex-bearish"}`}>
                      {r.realized_pnl >= 0 ? "+" : ""}${r.realized_pnl.toFixed(2)}
                    </span>
                    {r.equity != null && (
                      <span className="text-xs text-slate-300">${r.equity.toFixed(2)}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {!hasDailyData && (
          <div className="p-4 text-center text-sm text-slate-500">
            <AlertTriangle className="w-4 h-4 mx-auto mb-1 text-amber-400" />
            Historical equity data is sparse. More data will appear as trading continues.
          </div>
        )}
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  positive,
  negative,
  accent,
}: {
  label: string;
  value: string;
  positive?: boolean;
  negative?: boolean;
  accent?: boolean;
}) {
  let colorClass = "text-slate-200";
  if (positive === true) colorClass = "text-forex-bullish";
  if (positive === false) colorClass = "text-forex-bearish";
  if (negative) colorClass = "text-forex-bearish";
  if (accent) colorClass = "text-forex-accent font-bold";

  return (
    <div className="bg-slate-800/50 p-2 rounded text-center">
      <p className="text-[10px] text-slate-400 uppercase tracking-wider">{label}</p>
      <p className={`text-sm font-semibold ${colorClass}`}>{value}</p>
    </div>
  );
}
