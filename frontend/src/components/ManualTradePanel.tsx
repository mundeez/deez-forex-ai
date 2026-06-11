"use client";

import { useEffect, useState } from "react";
import { ArrowUpCircle, ArrowDownCircle, AlertTriangle } from "lucide-react";
import { API_URL } from "@/utils/api";

interface ManualTradePanelProps {
  symbol: string;
  onTrade?: () => void;
  visible?: boolean;
  provider?: string;
}

export default function ManualTradePanel({ symbol, onTrade, visible = true, provider = "metaapi" }: ManualTradePanelProps) {
  const [direction, setDirection] = useState<"buy" | "sell">("buy");
  const [entry, setEntry] = useState("");
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");
  const [lotSize, setLotSize] = useState("0.01");
  const [riskPct, setRiskPct] = useState("1.0");
  const [mode, setMode] = useState<"paper" | "live">("paper");
  const [providerState, setProviderState] = useState(provider);
  const [loading, setLoading] = useState(false);
  const [manualOverride, setManualOverride] = useState(false);

  useEffect(() => {
    fetchOverride();
  }, []);

  async function fetchOverride() {
    try {
      const res = await fetch(`${API_URL}/api/v1/manual-override`);
      if (!res.ok) return;
      const data = await res.json();
      setManualOverride(data.manual_override);
    } catch (e) {
      console.error("override fetch error", e);
    }
  }

  async function submitTrade() {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/trades/manual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol,
          direction,
          entry_price: entry ? parseFloat(entry) : undefined,
          stop_loss: sl ? parseFloat(sl) : undefined,
          take_profit: tp ? parseFloat(tp) : undefined,
          risk_pct: parseFloat(riskPct),
          position_size: parseFloat(lotSize),
          mode,
          provider: providerState,
        }),
      });
      if (res.ok && onTrade) onTrade();
      else if (!res.ok) {
        const err = await res.json();
        alert(`Trade failed: ${err.detail || "Unknown error"}`);
      }
    } catch (e) {
      console.error("trade submit error", e);
    } finally {
      setLoading(false);
    }
  }

  if (!visible && !manualOverride) {
    return (
      <div className="bg-forex-card rounded-xl border border-slate-700 p-4 text-center">
        <p className="text-sm text-slate-500">Manual trading hidden in auto mode</p>
        <p className="text-xs text-slate-600 mt-1">Enable Manual Override to trade</p>
      </div>
    );
  }

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">Manual Trade</h2>
        <span className={`text-[10px] px-2 py-0.5 rounded font-semibold ${
          mode === "live" ? "bg-red-900/50 text-red-300" : "bg-blue-900/50 text-blue-300"
        }`}>
          {mode.toUpperCase()}
        </span>
      </div>

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
          <label className="text-xs text-slate-400">Entry Price (optional)</label>
          <input
            type="number"
            step="0.00001"
            value={entry}
            onChange={(e) => setEntry(e.target.value)}
            placeholder="Market execution"
            className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 mt-0.5 text-sm"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-xs text-slate-400">Stop Loss</label>
            <input type="number" step="0.00001" value={sl} onChange={(e) => setSl(e.target.value)} className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 mt-0.5 text-sm" />
          </div>
          <div>
            <label className="text-xs text-slate-400">Take Profit</label>
            <input type="number" step="0.00001" value={tp} onChange={(e) => setTp(e.target.value)} className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 mt-0.5 text-sm" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-xs text-slate-400">Lot Size</label>
            <input type="number" step="0.01" min="0.01" value={lotSize} onChange={(e) => setLotSize(e.target.value)} className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 mt-0.5 text-sm" />
          </div>
          <div>
            <label className="text-xs text-slate-400">Risk %</label>
            <input type="number" step="0.1" value={riskPct} onChange={(e) => setRiskPct(e.target.value)} className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 mt-0.5 text-sm" />
          </div>
        </div>

        <div className="flex items-center gap-2 pt-1">
          <label className="text-xs text-slate-400">Broker:</label>
          <select
            value={providerState}
            onChange={(e) => setProviderState(e.target.value)}
            className="text-xs bg-slate-800 text-slate-300 border border-slate-600 rounded px-1 py-0.5"
          >
            <option value="metaapi">MetaAPI.cloud</option>
            <option value="mt5_zmq">MT5 Container (ZMQ)</option>
          </select>
        </div>

        <div className="flex items-center gap-2 pt-1">
          <label className="text-xs text-slate-400">Mode:</label>
          <button
            onClick={() => setMode("paper")}
            className={`text-xs px-2 py-0.5 rounded ${mode === "paper" ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400"}`}
          >
            Paper
          </button>
          <button
            onClick={() => setMode("live")}
            className={`text-xs px-2 py-0.5 rounded flex items-center gap-1 ${mode === "live" ? "bg-red-600 text-white" : "bg-slate-800 text-slate-400"}`}
          >
            {mode === "live" && <AlertTriangle className="w-3 h-3" />}
            Live
          </button>
        </div>
      </div>

      <button
        onClick={submitTrade}
        disabled={loading}
        className={`w-full mt-3 py-2 rounded-lg font-semibold text-sm transition ${
          direction === "buy" ? "bg-emerald-600 hover:bg-emerald-500" : "bg-red-600 hover:bg-red-500"
        } text-white disabled:opacity-50`}
      >
        {loading ? "Submitting..." : `Place ${direction.toUpperCase()} ${mode.toUpperCase()}`}
      </button>
    </div>
  );
}
