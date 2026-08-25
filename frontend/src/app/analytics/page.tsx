"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, BarChart3 } from "lucide-react";
import { API_URL } from "@/utils/api";
import { usePolling, fetchJSON } from "@/hooks/usePolling";
import { PortfolioSummary, SessionAnalytics, HourAnalytics, HoldingBucket } from "@/types";
import { formatNumber, formatPnl } from "@/utils/format";

export default function AnalyticsPage() {
  const router = useRouter();
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [sessions, setSessions] = useState<SessionAnalytics[]>([]);
  const [hours, setHours] = useState<HourAnalytics[]>([]);
  const [buckets, setBuckets] = useState<HoldingBucket[]>([]);
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<any>(null);

  usePolling(
    async (signal) => {
      const [p, s, h, b] = await Promise.all([
        fetchJSON<PortfolioSummary>(`${API_URL}/api/v1/analytics/portfolio`, signal),
        fetchJSON<{ sessions: SessionAnalytics[] }>(`${API_URL}/api/v1/analytics/by-session`, signal),
        fetchJSON<{ hours: HourAnalytics[] }>(`${API_URL}/api/v1/analytics/by-hour`, signal),
        fetchJSON<{ buckets: HoldingBucket[] }>(`${API_URL}/api/v1/analytics/holding-distribution`, signal),
      ]);
      if (p) setPortfolio(p);
      if (s) setSessions(s.sessions);
      if (h) setHours(h.hours);
      if (b) setBuckets(b.buckets);
    },
    30000,
    []
  );

  useEffect(() => {
    if (!chartContainerRef.current || !portfolio?.equity_history?.length) return;
    let isMounted = true;

    const initChart = async () => {
      const { createChart } = await import("lightweight-charts");
      if (!isMounted || !chartContainerRef.current) return;

      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }

      const chart = createChart(chartContainerRef.current, {
        layout: {
          background: { color: "#0f172a" },
          textColor: "#94a3b8",
        },
        grid: {
          vertLines: { color: "#1e293b" },
          horzLines: { color: "#1e293b" },
        },
        rightPriceScale: {
          borderColor: "#334155",
        },
        timeScale: {
          borderColor: "#334155",
          timeVisible: true,
          secondsVisible: false,
        },
      });

      const area = chart.addAreaSeries({
        topColor: "rgba(59, 130, 246, 0.4)",
        bottomColor: "rgba(59, 130, 246, 0.05)",
        lineColor: "#3b82f6",
        lineWidth: 2,
      });

      area.setData(
        portfolio.equity_history.map((pt) => ({
          time: new Date(pt.timestamp).getTime() / 1000 as any,
          value: pt.equity,
        }))
      );

      chart.timeScale().fitContent();
      chartRef.current = chart;
    };

    initChart();

    const handleResize = () => {
      if (chartRef.current && chartContainerRef.current) {
        chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      isMounted = false;
      window.removeEventListener("resize", handleResize);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [portfolio?.equity_history]);

  return (
    <div className="min-h-screen bg-forex-bg text-slate-200 p-4 md:p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push("/")}
              className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 transition"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
            <div>
              <h1 className="text-2xl font-bold text-white flex items-center gap-2">
                <BarChart3 className="w-6 h-6 text-forex-accent" />
                Analytics
              </h1>
              <p className="text-sm text-slate-400">Portfolio performance, session breakdown, and holding distribution</p>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricTile label="Equity" value={formatNumber(portfolio?.equity)} />
          <MetricTile label="Realized PnL" value={formatPnl(portfolio?.realized_pnl)} />
          <MetricTile label="Max Drawdown" value={`${portfolio?.max_drawdown_pct ?? "-"}%`} />
          <MetricTile label="Sharpe" value={portfolio?.sharpe_ratio ?? "-"} />
          <MetricTile label="Sortino" value={portfolio?.sortino_ratio ?? "-"} />
          <MetricTile label="Calmar" value={portfolio?.calmar_ratio ?? "-"} />
          <MetricTile label="Win Rate" value={`${portfolio?.win_rate ?? "-"}%`} />
          <MetricTile label="Profit Factor" value={portfolio?.profit_factor ?? "-"} />
        </div>

        <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
          <h2 className="text-lg font-semibold text-white mb-4">Equity Curve</h2>
          <div ref={chartContainerRef} className="w-full h-80" />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
            <h2 className="text-lg font-semibold text-white mb-4">By Session</h2>
            <div className="space-y-3">
              {sessions.length === 0 && <p className="text-sm text-slate-500">No closed trades yet.</p>}
              {sessions.map((s) => (
                <div key={s.session} className="flex items-center justify-between p-3 bg-slate-900 rounded-lg">
                  <div>
                    <div className="text-sm font-medium text-white capitalize">{s.session.replace(/_/g, " ")}</div>
                    <div className="text-xs text-slate-500">{s.total_trades} trades · {s.winning_trades}W/{s.losing_trades}L</div>
                  </div>
                  <div className="text-right">
                    <div className={`text-sm font-semibold ${s.total_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {formatPnl(s.total_pnl)}
                    </div>
                    <div className="text-xs text-slate-500">WR {s.win_rate ?? "-"}% · PF {s.profit_factor ?? "-"}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
            <h2 className="text-lg font-semibold text-white mb-4">By Hour (UTC)</h2>
            <div className="space-y-2 max-h-80 overflow-y-auto">
              {hours.length === 0 && <p className="text-sm text-slate-500">No closed trades yet.</p>}
              {hours.map((h) => (
                <div key={h.hour} className="flex items-center justify-between p-2 bg-slate-900 rounded-lg">
                  <div className="text-sm font-medium text-white w-16">{String(h.hour).padStart(2, "0")}:00</div>
                  <div className="flex-1 mx-3">
                    <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full ${h.total_pnl >= 0 ? "bg-green-500" : "bg-red-500"}`}
                        style={{ width: `${Math.min(Math.abs(h.total_pnl) * 2, 100)}%` }}
                      />
                    </div>
                  </div>
                  <div className="text-right min-w-[5rem]">
                    <div className={`text-sm font-semibold ${h.total_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {formatPnl(h.total_pnl)}
                    </div>
                    <div className="text-xs text-slate-500">{h.total_trades}T · {h.win_rate ?? "-"}%</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
          <h2 className="text-lg font-semibold text-white mb-4">Holding Distribution</h2>
          <div className="space-y-3">
            {buckets.length === 0 && <p className="text-sm text-slate-500">No closed trades yet.</p>}
            {buckets.map((b) => (
              <div key={b.bucket} className="flex items-center gap-4">
                <div className="w-24 text-sm text-slate-300">{b.bucket}</div>
                <div className="flex-1">
                  <div className="h-4 bg-slate-800 rounded overflow-hidden flex">
                    {b.total_trades > 0 && (
                      <>
                        <div
                          className="h-full bg-green-500"
                          style={{ width: `${(b.winning_trades / b.total_trades) * 100}%` }}
                        />
                        <div
                          className="h-full bg-red-500"
                          style={{ width: `${(b.losing_trades / b.total_trades) * 100}%` }}
                        />
                      </>
                    )}
                  </div>
                </div>
                <div className="w-32 text-right text-sm">
                  <span className={b.total_pnl >= 0 ? "text-green-400" : "text-red-400"}>{formatPnl(b.total_pnl)}</span>
                </div>
                <div className="w-20 text-right text-xs text-slate-500">{b.total_trades} trades</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function MetricTile({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="text-xs text-slate-400 mb-1">{label}</div>
      <div className="text-lg font-semibold text-white">{value ?? "-"}</div>
    </div>
  );
}
