"use client";

import { useState } from "react";
import { ArrowUpCircle, ArrowDownCircle } from "lucide-react";
import { API_URL } from "@/utils/api";

interface ManualTradePanelProps {
  symbol: string;
  onTrade?: () => void;
}

export default function ManualTradePanel({ symbol, onTrade }: ManualTradePanelProps) {
  const [direction, setDirection] = useState<"buy" | "sell">("buy");
  const [entry, setEntry] = useState("");
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");
  const [riskPct, setRiskPct] = useState("1.0");
  const [loading, setLoading] = useState(false);

  async function submitTrade() {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/trades`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol,
          direction,
          entry_price: parseFloat(entry),
          stop_loss: sl ? parseFloat(sl) : undefined,
          take_profit: tp ? parseFloat(tp) : undefined,
          risk_pct: parseFloat(riskPct),
          mode: "paper",
        }),
      });
      if (res.ok && onTrade) onTrade();
    } catch (e) {
      console.error("trade submit error", e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <h2 className="text-lg font-semibold mb-3">Manual Trade</h2>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <button
          onClick={() => setDirection("buy")}
          className={`flex items-center justify-center gap-2 py-2 rounded-lg font-semibold text-sm transition ${
            direction === "buy" ? "bg-emerald-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700"
          }`}
        >
          <ArrowUpCircle className="w-4 h-4" /> BUY
        </button>
        <button
          onClick={() => setDirection("sell")}
          className={`flex items-center justify-center gap-2 py-2 rounded-lg font-semibold text-sm transition ${
            direction === "sell" ? "bg-red-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700"
          }`}
        >
          <ArrowDownCircle className="w-4 h-4" /> SELL
        </button>
      </div>

      <div className="space-y-2 text-sm">
        <div>
          <label className="text-xs text-slate-400">Entry Price</label>
          <input type="number" step="0.00001" value={entry} onChange={(e) => setEntry(e.target.value)} className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 mt-0.5" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-xs text-slate-400">Stop Loss</label>
            <input type="number" step="0.00001" value={sl} onChange={(e) => setSl(e.target.value)} className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 mt-0.5" />
          </div>
          <div>
            <label className="text-xs text-slate-400">Take Profit</label>
            <input type="number" step="0.00001" value={tp} onChange={(e) => setTp(e.target.value)} className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 mt-0.5" />
          </div>
        </div>
        <div>
          <label className="text-xs text-slate-400">Risk %</label>
          <input type="number" step="0.1" value={riskPct} onChange={(e) => setRiskPct(e.target.value)} className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 mt-0.5" />
        </div>
      </div>

      <button
        onClick={submitTrade}
        disabled={loading || !entry}
        className={`w-full mt-3 py-2 rounded-lg font-semibold text-sm transition ${
          direction === "buy" ? "bg-emerald-600 hover:bg-emerald-500" : "bg-red-600 hover:bg-red-500"
        } text-white disabled:opacity-50`}
      >
        {loading ? "Submitting..." : `Place ${direction.toUpperCase()}`}
      </button>
    </div>
  );
}
