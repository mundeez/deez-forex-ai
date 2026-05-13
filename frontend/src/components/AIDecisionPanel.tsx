"use client";

import { useEffect, useState } from "react";
import { Bot, CheckCircle, XCircle, AlertTriangle } from "lucide-react";
import { API_URL } from "@/utils/api";

export default function AIDecisionPanel() {
  const [decisions, setDecisions] = useState<any[]>([]);
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

  async function fetchDecisions() {
    try {
      const res = await fetch(`${API_URL}/api/v1/ai-decisions?limit=5`);
      if (!res.ok) return;
      const data = await res.json();
      setDecisions(data.decisions || []);
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

  async function approveDecision(decision: any) {
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

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="flex items-center gap-2 mb-3">
        <Bot className="w-5 h-5 text-forex-accent" />
        <h2 className="text-lg font-semibold">AI Decisions</h2>
      </div>

      {decisions.length === 0 ? (
        <p className="text-sm text-slate-500">No recent AI decisions</p>
      ) : (
        <div className="space-y-2 max-h-72 overflow-auto">
          {decisions.map((d: any) => {
            const decisionColor = d.decision === "BUY" ? "text-forex-bullish" : d.decision === "SELL" ? "text-forex-bearish" : "text-slate-400";
            const DecisionIcon = d.decision === "BUY" ? CheckCircle : d.decision === "SELL" ? XCircle : AlertTriangle;
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
                  </div>
                )}
                {manualOverride && (d.decision === "BUY" || d.decision === "SELL") && (
                  <div className="flex gap-2 mt-2">
                    <button
                      onClick={() => approveDecision(d)}
                      className="px-2 py-1 bg-forex-bullish text-white text-xs rounded hover:bg-green-600"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => alert("Decision rejected")}
                      className="px-2 py-1 bg-forex-bearish text-white text-xs rounded hover:bg-red-600"
                    >
                      Reject
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
