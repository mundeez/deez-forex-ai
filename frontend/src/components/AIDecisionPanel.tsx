"use client";

import { useEffect, useState } from "react";
import { Bot, CheckCircle, XCircle, AlertTriangle, TrendingUp, TrendingDown } from "lucide-react";
import { API_URL } from "@/utils/api";

interface AIDecision {
  id: number;
  symbol: string;
  decision: string;
  confidence: number;
  timeframe?: string;
  entry_price?: number;
  stop_loss?: number;
  take_profit?: number;
  position_size_pct?: number;
  risk_reward?: number;
  rationale?: string;
  manual_override?: boolean;
}

export default function AIDecisionPanel({ newDecisions = [] }: { newDecisions?: AIDecision[] }) {
  const [decisions, setDecisions] = useState<AIDecision[]>([]);
  const [manualOverride, setManualOverride] = useState(false);

  useEffect(() => {
    fetchDecisions();
    fetchOverride();
    const interval = setInterval(() => {
      fetchDecisions();
      fetchOverride();
    }, 15000);
    return () => clearInterval(interval);
  }, []);

  // Merge WebSocket decisions
  useEffect(() => {
    if (newDecisions.length > 0) {
      setDecisions((prev) => {
        const merged = [...newDecisions, ...prev];
        // Remove duplicates by id
        const seen = new Set();
        return merged.filter((d) => {
          if (seen.has(d.id)) return false;
          seen.add(d.id);
          return true;
        });
      });
    }
  }, [newDecisions]);

  async function fetchDecisions() {
    try {
      const res = await fetch(`${API_URL}/api/v1/ai/decisions?limit=5`);
      if (!res.ok) return;
      const data = await res.json();
      setDecisions((prev) => {
        const fetched = data || [];
        const merged = [...fetched, ...prev];
        const seen = new Set();
        return merged.filter((d) => {
          if (seen.has(d.id)) return false;
          seen.add(d.id);
          return true;
        }).slice(0, 10);
      });
    } catch (e) {
      console.error("ai decisions fetch error", e);
    }
  }

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

  async function approveDecision(decision: AIDecision) {
    try {
      const res = await fetch(`${API_URL}/api/v1/trades/manual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: decision.symbol,
          direction: decision.decision.toLowerCase(),
          entry_price: decision.entry_price,
          stop_loss: decision.stop_loss,
          take_profit: decision.take_profit,
          risk_pct: decision.position_size_pct,
          mode: "paper",
          rationale: `Approved AI decision: ${decision.rationale}`,
        }),
      });
      if (res.ok) {
        alert("Trade executed successfully");
      } else {
        const err = await res.json();
        alert(`Trade failed: ${err.detail || "Unknown error"}`);
      }
    } catch (e) {
      console.error("approve error", e);
    }
  }

  function rejectDecision(decision: AIDecision) {
    setDecisions((prev) => prev.filter((d) => d.id !== decision.id));
  }

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Bot className="w-5 h-5 text-forex-accent" />
          <h2 className="text-lg font-semibold">AI Decisions</h2>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded ${manualOverride ? "bg-amber-900/50 text-amber-300" : "bg-emerald-900/50 text-emerald-300"}`}>
          {manualOverride ? "Manual" : "Auto"}
        </span>
      </div>

      {decisions.length === 0 ? (
        <p className="text-sm text-slate-500">No recent AI decisions</p>
      ) : (
        <div className="space-y-2 max-h-72 overflow-auto">
          {decisions.map((d) => {
            const decisionColor = d.decision === "BUY" ? "text-forex-bullish" : d.decision === "SELL" ? "text-forex-bearish" : "text-slate-400";
            const DecisionIcon = d.decision === "BUY" ? TrendingUp : d.decision === "SELL" ? TrendingDown : AlertTriangle;
            return (
              <div key={d.id} className="bg-slate-800/50 p-3 rounded-lg text-sm">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <DecisionIcon className={`w-4 h-4 ${decisionColor}`} />
                    <span className="font-bold">{d.symbol}</span>
                    <span className={`font-semibold ${decisionColor}`}>{d.decision}</span>
                  </div>
                  <span className="text-xs text-slate-500">{(d.confidence * 100).toFixed(0)}%</span>
                </div>
                <p className="text-xs text-slate-400 line-clamp-2">{d.rationale}</p>
                {d.entry_price && (
                  <div className="flex gap-3 mt-2 text-xs text-slate-500">
                    <span>Entry: {d.entry_price}</span>
                    <span>SL: {d.stop_loss}</span>
                    <span>TP: {d.take_profit}</span>
                    {d.risk_reward && <span>RR: {d.risk_reward}:1</span>}
                  </div>
                )}
                {manualOverride && (d.decision === "BUY" || d.decision === "SELL") && (
                  <div className="flex gap-2 mt-2">
                    <button
                      onClick={() => approveDecision(d)}
                      className="flex-1 px-2 py-1 bg-forex-bullish text-white text-xs rounded hover:bg-green-600 transition flex items-center justify-center gap-1"
                    >
                      <CheckCircle className="w-3 h-3" /> Approve
                    </button>
                    <button
                      onClick={() => rejectDecision(d)}
                      className="flex-1 px-2 py-1 bg-forex-bearish text-white text-xs rounded hover:bg-red-600 transition flex items-center justify-center gap-1"
                    >
                      <XCircle className="w-3 h-3" /> Reject
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
