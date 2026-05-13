"use client";

import { useEffect, useState } from "react";
import { Plus, X, Settings } from "lucide-react";
import { API_URL } from "@/utils/api";

interface PairSelectorProps {
  onChange?: (pairs: string[]) => void;
}

const AVAILABLE_PAIRS = [
  "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD"
];

export default function PairSelector({ onChange }: PairSelectorProps) {
  const [pairs, setPairs] = useState<any[]>([]);
  const [showAdd, setShowAdd] = useState(false);

  useEffect(() => {
    fetchPairs();
  }, []);

  async function fetchPairs() {
    try {
      const res = await fetch(`${API_URL}/api/v1/pairs`);
      if (!res.ok) return;
      const data = await res.json();
      setPairs(data.pairs || []);
      if (onChange) onChange(data.pairs.map((p: any) => p.symbol));
    } catch (e) {
      console.error("pairs fetch error", e);
    }
  }

  async function addPair(symbol: string) {
    try {
      const res = await fetch(`${API_URL}/api/v1/pairs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, selection_mode: "manual", priority: pairs.length + 1 }),
      });
      if (res.ok) {
        fetchPairs();
        setShowAdd(false);
      }
    } catch (e) {
      console.error("add pair error", e);
    }
  }

  async function removePair(id: number) {
    try {
      const res = await fetch(`${API_URL}/api/v1/pairs/${id}`, { method: "DELETE" });
      if (res.ok) fetchPairs();
    } catch (e) {
      console.error("remove pair error", e);
    }
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
        {pairs.map((p: any) => (
          <div key={p.id} className="flex items-center justify-between bg-slate-800/50 p-2 rounded-lg">
            <div>
              <span className="font-semibold text-sm">{p.symbol}</span>
              <span className="text-xs text-slate-500 ml-2 capitalize">{p.selection_mode}</span>
            </div>
            <button onClick={() => removePair(p.id)} className="text-slate-500 hover:text-red-400">
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
              className="bg-slate-800 hover:bg-slate-700 text-xs py-1 rounded border border-slate-600"
            >
              {sym}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
