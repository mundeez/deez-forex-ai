"use client";

import { useEffect, useState } from "react";
import { XCircle, TrendingUp, TrendingDown, Clock, Target, Shield } from "lucide-react";
import { API_URL } from "@/utils/api";

interface Position {
  id: number;
  symbol: string;
  direction: string;
  entry_price: number;
  stop_loss?: number;
  take_profit?: number;
  pnl?: number;
  pnl_pct?: number;
  open_time?: string;
  duration_minutes?: number;
  distance_to_sl?: number;
  distance_to_tp?: number;
  mode: string;
}

export default function PositionsPanel({ onRefresh }: { onRefresh?: () => void }) {
  const [positions, setPositions] = useState<Position[]>([]);

  useEffect(() => {
    fetchPositions();
    const interval = setInterval(fetchPositions, 10000);
    return () => clearInterval(interval);
  }, []);

  async function fetchPositions() {
    try {
      const res = await fetch(`${API_URL}/api/v1/positions`);
      if (!res.ok) return;
      const data = await res.json();
      setPositions(data.positions || []);
    } catch (e) {
      console.error("positions fetch error", e);
    }
  }

  async function closePosition(id: number) {
    try {
      const res = await fetch(`${API_URL}/api/v1/positions/${id}/close`, { method: "POST" });
      if (res.ok) {
        fetchPositions();
        if (onRefresh) onRefresh();
      }
    } catch (e) {
      console.error("close error", e);
    }
  }

  function formatDuration(minutes?: number) {
    if (!minutes) return "-";
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <h2 className="text-lg font-semibold mb-3">Open Positions ({positions.length})</h2>
      {positions.length === 0 ? (
        <p className="text-sm text-slate-500">No open positions</p>
      ) : (
        <div className="space-y-2 max-h-80 overflow-auto">
          {positions.map((p) => (
            <div key={p.id} className="bg-slate-800/50 p-3 rounded-lg text-sm">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  {p.direction === "buy" ? (
                    <TrendingUp className="w-4 h-4 text-forex-bullish" />
                  ) : (
                    <TrendingDown className="w-4 h-4 text-forex-bearish" />
                  )}
                  <div>
                    <p className="font-semibold">{p.symbol}</p>
                    <p className="text-xs text-slate-400">
                      {p.direction.toUpperCase()} @ {p.entry_price?.toFixed(5)}
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <p className={`font-bold ${(p.pnl || 0) >= 0 ? "text-forex-bullish" : "text-forex-bearish"}`}>
                    {p.pnl && p.pnl >= 0 ? "+" : ""}${p.pnl?.toFixed(2) || "0.00"}
                  </p>
                  <p className="text-xs text-slate-400">{p.pnl_pct?.toFixed(2) || "0.00"}%</p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-2 text-xs text-slate-400">
                <div className="flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  <span>{formatDuration(p.duration_minutes)}</span>
                </div>
                <div className="flex items-center gap-1">
                  <Shield className="w-3 h-3 text-red-400" />
                  <span>SL: {p.distance_to_sl?.toFixed(1) || "-"} pips</span>
                </div>
                <div className="flex items-center gap-1">
                  <Target className="w-3 h-3 text-emerald-400" />
                  <span>TP: {p.distance_to_tp?.toFixed(1) || "-"} pips</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] ${p.mode === "live" ? "bg-red-900/50 text-red-300" : "bg-blue-900/50 text-blue-300"}`}>
                    {p.mode.toUpperCase()}
                  </span>
                </div>
              </div>

              <button
                onClick={() => closePosition(p.id)}
                className="w-full mt-2 text-xs text-red-400 hover:text-red-300 flex items-center justify-center gap-1 py-1 border border-red-900/50 rounded hover:bg-red-900/20 transition"
              >
                <XCircle className="w-3 h-3" /> Close Position
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
