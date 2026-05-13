"use client";

import { useEffect, useState } from "react";
import { Plus, X, Settings, Zap, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { API_URL } from "@/utils/api";

interface PairSlot {
  id?: number;
  symbol: string;
  selection_mode: string;
  priority: number;
  signal_strength?: number;
}

interface PairSelectorProps {
  onChange?: (pairs: string[]) => void;
}

const AVAILABLE_PAIRS = [
  "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD"
];

export default function PairSelector({ onChange }: PairSelectorProps) {
  const [pairs, setPairs] = useState<PairSlot[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [activePairs, setActivePairs] = useState<string[]>([]);

  useEffect(() => {
    fetchPairs();
  }, []);

  async function fetchPairs() {
    try {
      const res = await fetch(`${API_URL}/api/v1/pairs/active`);
      if (!res.ok) return;
      const data = await res.json();
      const fetchedPairs: PairSlot[] = data || [];
      setPairs(fetchedPairs);
      setActivePairs(fetchedPairs.map((p) => p.symbol));
      if (onChange) onChange(fetchedPairs.map((p) => p.symbol));

      // Fetch signal strength for auto pairs
      fetchedPairs.forEach(async (p) => {
        if (p.selection_mode === "auto") {
          try {
            const analysisRes = await fetch(`${API_URL}/api/v1/analysis/summary?symbol=${p.symbol}`);
            if (analysisRes.ok) {
              const analysis = await analysisRes.json();
              // Simple signal strength based on combined signal
              const strength = analysis.combined_signal === "bullish" ? 0.7 : analysis.combined_signal === "bearish" ? -0.7 : 0;
              setPairs((prev) => prev.map((pair) =>
                pair.symbol === p.symbol ? { ...pair, signal_strength: strength } : pair
              ));
            }
          } catch {
            // ignore
          }
        }
      });
    } catch (e) {
      console.error("pairs fetch error", e);
    }
  }

  async function updateActivePairs(newPairs: PairSlot[]) {
    try {
      const payload = newPairs.map((p) => ({
        symbol: p.symbol,
        selection_mode: p.selection_mode,
        priority: p.priority,
      }));
      const res = await fetch(`${API_URL}/api/v1/pairs/active`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        fetchPairs();
        setShowAdd(false);
      }
    } catch (e) {
      console.error("update pairs error", e);
    }
  }

  function addPair(symbol: string) {
    const newPairs = [...pairs, { symbol, selection_mode: "manual", priority: pairs.length + 1 }];
    updateActivePairs(newPairs);
  }

  function removePair(index: number) {
    const newPairs = pairs.filter((_, i) => i !== index).map((p, i) => ({ ...p, priority: i + 1 }));
    updateActivePairs(newPairs);
  }

  function toggleMode(index: number) {
    const newPairs = pairs.map((p, i) =>
      i === index ? { ...p, selection_mode: p.selection_mode === "auto" ? "manual" : "auto" } : p
    );
    updateActivePairs(newPairs);
  }

  const used = pairs.map((p) => p.symbol);
  const availableToAdd = AVAILABLE_PAIRS.filter((s) => !used.includes(s));

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Settings className="w-5 h-5 text-forex-accent" />
          <h2 className="text-lg font-semibold">Active Pairs</h2>
        </div>
        {pairs.length < 3 && (
          <button onClick={() => setShowAdd(!showAdd)} className="text-xs text-forex-accent hover:underline flex items-center gap-1">
            <Plus className="w-3 h-3" /> Add
          </button>
        )}
      </div>

      <div className="space-y-2">
        {pairs.map((p, idx) => (
          <div key={`${p.symbol}-${idx}`} className="flex items-center justify-between bg-slate-800/50 p-2 rounded-lg">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm">{p.symbol}</span>
              <button
                onClick={() => toggleMode(idx)}
                className={`text-[10px] px-1.5 py-0.5 rounded border transition ${
                  p.selection_mode === "auto"
                    ? "border-amber-600 text-amber-400 bg-amber-900/20"
                    : "border-slate-600 text-slate-400 bg-slate-800"
                }`}
              >
                {p.selection_mode === "auto" ? (
                  <span className="flex items-center gap-1"><Zap className="w-3 h-3" /> Auto</span>
                ) : (
                  "Manual"
                )}
              </button>
              {p.signal_strength !== undefined && (
                <span className={`text-xs ${p.signal_strength > 0 ? "text-forex-bullish" : p.signal_strength < 0 ? "text-forex-bearish" : "text-slate-400"}`}>
                  {p.signal_strength > 0 ? <TrendingUp className="w-3 h-3 inline" /> : p.signal_strength < 0 ? <TrendingDown className="w-3 h-3 inline" /> : <Minus className="w-3 h-3 inline" />}
                </span>
              )}
            </div>
            <button onClick={() => removePair(idx)} className="text-slate-500 hover:text-red-400 transition">
              <X className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>

      {showAdd && availableToAdd.length > 0 && (
        <div className="mt-2 grid grid-cols-3 gap-2">
          {availableToAdd.map((sym) => (
            <button
              key={sym}
              onClick={() => addPair(sym)}
              className="bg-slate-800 hover:bg-slate-700 text-xs py-1 rounded border border-slate-600 transition"
            >
              {sym}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
