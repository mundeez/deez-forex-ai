"use client";

import { useEffect, useState } from "react";
import { API_URL } from "@/utils/api";

export default function PaperTradingPage() {
  const [report, setReport] = useState<any>({});
  const [goNoGo, setGoNoGo] = useState<any>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/paper-trading/report?days=30`).then(r => r.json()).then(setReport).catch(() => {});
    fetch(`${API_URL}/api/v1/paper-trading/go-no-go?days=30`).then(r => r.json()).then(setGoNoGo).then(() => setLoading(false)).catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8 text-slate-300">Loading paper trading metrics...</div>;

  const checks = goNoGo.checks || {};
  const passed = goNoGo.passed || 0;
  const total = goNoGo.total_criteria || 8;

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold mb-2 text-white">Paper Trading Validation</h1>
      <p className="text-slate-400 text-sm mb-6">30-day monitoring period — Sprint 6</p>

      {/* Go/No-Go Banner */}
      <div className={`rounded-xl p-4 mb-6 border ${goNoGo.go ? "bg-emerald-900/30 border-emerald-700" : "bg-amber-900/30 border-amber-700"}`}>
        <div className="flex items-center justify-between">
          <div>
            <h2 className={`text-lg font-bold ${goNoGo.go ? "text-emerald-400" : "text-amber-400"}`}>
              {goNoGo.go ? "GO — Ready for Live Deployment" : "NO-GO — Criteria Not Met"}
            </h2>
            <p className="text-slate-300 text-sm mt-1">
              {passed} of {total} acceptance criteria passed
            </p>
          </div>
          <div className="text-right">
            <p className="text-3xl font-bold text-white">{passed}/{total}</p>
          </div>
        </div>
      </div>

      {/* Criteria Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        {Object.entries(checks).map(([key, val]: [string, any]) => {
          const labels: Record<string, string> = {
            win_rate_ge_52: "Win Rate >= 52%",
            profit_factor_ge_1_2: "Profit Factor >= 1.2",
            max_daily_dd_le_3pct: "Daily DD <= 3%",
            exit_quality_ge_0_55: "Exit Quality >= 0.55",
            min_100_trades: ">= 100 Trades",
            rag_coverage_ge_90: "RAG Coverage >= 90%",
            gate_filter_15_30: "Gate Filter 15-30%",
            zero_emergency_stops: "Zero Emergency Stops",
          };
          return (
            <div key={key} className={`rounded-lg p-3 border ${val ? "bg-emerald-900/20 border-emerald-800" : "bg-red-900/20 border-red-800"}`}>
              <div className="flex items-center gap-2">
                <span className={`text-lg ${val ? "text-emerald-400" : "text-red-400"}`}>{val ? "✓" : "✗"}</span>
                <span className="text-xs text-slate-300">{labels[key] || key}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <MetricCard label="Total Trades" value={report.total_trades} sub={`Win Rate: ${(report.win_rate * 100).toFixed(1)}%`} color="blue" />
        <MetricCard label="Profit Factor" value={report.profit_factor} sub={`Net PnL: $${report.net_pnl}`} color="emerald" />
        <MetricCard label="Exit Quality" value={report.avg_exit_quality} sub={`Avg Score (0-100)`} color="purple" />
        <MetricCard label="RAG Coverage" value={`${(report.rag_outcome_coverage * 100).toFixed(0)}%`} sub={`${report.total_decisions} decisions`} color="cyan" />
        <MetricCard label="Gate Filter Rate" value={`${(report.xgb_gate_filter_rate * 100).toFixed(1)}%`} sub={`${report.xgb_gate_blocked} blocked`} color="amber" />
        <MetricCard label="Emergency Stops" value={report.emergency_stops} sub={report.emergency_stops === 0 ? "Clean" : "ALERT"} color={report.emergency_stops === 0 ? "emerald" : "red"} />
      </div>

      {/* Drawdown */}
      <div className="bg-slate-800 rounded-xl p-4 border border-slate-700 mb-6">
        <h2 className="text-lg font-semibold mb-3 text-white">Drawdown</h2>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-slate-400">Max Single-Day DD</span>
            <p className="text-xl font-mono text-white">${report.max_single_day_drawdown}</p>
          </div>
          <div>
            <span className="text-slate-400">Max DD %</span>
            <p className="text-xl font-mono text-white">{report.max_drawdown_pct}%</p>
          </div>
        </div>
      </div>

      {/* Open Positions */}
      <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
        <h2 className="text-lg font-semibold mb-3 text-white">Open Positions</h2>
        <div className="flex justify-between text-sm">
          <span className="text-slate-400">Count</span>
          <span className="text-white font-mono">{report.open_positions}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-slate-400">Unrealized PnL</span>
          <span className={`font-mono ${report.unrealized_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {report.unrealized_pnl >= 0 ? "+" : ""}${report.unrealized_pnl}
          </span>
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value, sub, color }: { label: string; value: any; sub: string; color: string }) {
  const colorMap: Record<string, string> = {
    blue: "text-blue-400",
    emerald: "text-emerald-400",
    purple: "text-purple-400",
    cyan: "text-cyan-400",
    amber: "text-amber-400",
    red: "text-red-400",
  };
  return (
    <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
      <p className="text-xs text-slate-400 uppercase">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${colorMap[color] || "text-white"}`}>{value}</p>
      <p className="text-xs text-slate-500 mt-1">{sub}</p>
    </div>
  );
}
