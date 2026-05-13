"use client";

import { useEffect, useState } from "react";
import { XCircle, TrendingUp, TrendingDown } from "lucide-react";
import { API_URL } from "@/utils/api";

export default function PositionsPanel({ onRefresh }: { onRefresh?: () => void }) {
  const [positions, setPositions] = useState<any[]>([]);

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

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <h2 className="text-lg font-semibold mb-3">Open Positions</h2>
      {positions.length === 0 ? (
        <p className="text-sm text-slate-500">No open positions</p>
      ) : (
        <div className="space-y-2 max-h-64 overflow-auto">
          {positions.map((p: any) => (
            <div key={p.id} className="flex items-center justify-between bg-slate-800/50 p-2 rounded-lg text-sm">
              <div className="flex items-center gap-2">
                {p.direction === "long" ? (
                  <TrendingUp className="w-4 h-4 text-forex-bullish" />
                ) : (
                  <TrendingDown className="w-4 h-4 text-forex-bearish" />
                )}
                <div>
                  <p className="font-semibold">{p.symbol}</p>
                  <p className="text-xs text-slate-400">
                    {p.direction.toUpperCase()} @ {p.entry_price}
                  </p>
                </div>
              </div>
              <div className="text-right">
                <p className={`font-bold ${p.pnl >= 0 ? "text-forex-bullish" : "text-forex-bearish"}`}>
                  {p.pnl >= 0 ? "+" : ""}${p.pnl.toFixed(2)}
                </p>
                <button
                  onClick={() => closePosition(p.id)}
                  className="text-xs text-red-400 hover:text-red-300 flex items-center gap-1 mt-1"
                >
                  <XCircle className="w-3 h-3" /> Close
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
