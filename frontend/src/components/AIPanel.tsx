"use client";

import { Brain, RefreshCw, AlertTriangle } from "lucide-react";

interface AIPanelProps {
  decisions: any[];
  onAnalyze: () => void;
  loading: boolean;
}

export default function AIPanel({ decisions, onAnalyze, loading }: AIPanelProps) {
  const latest = decisions[0];

  const getDecisionColor = (decision: string) => {
    if (decision === "BUY") return "text-green-400";
    if (decision === "SELL") return "text-red-400";
    return "text-slate-300";
  };

  return (
    <div className="bg-forex-card rounded-xl p-6 border border-slate-700">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Brain className="w-5 h-5 text-forex-accent" />
          <h2 className="text-lg font-semibold">AI Decision Engine</h2>
        </div>
        <button
          onClick={onAnalyze}
          disabled={loading}
          className="flex items-center gap-2 bg-forex-accent hover:bg-blue-600 text-white text-sm px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          {loading ? "Analyzing..." : "Run Analysis"}
        </button>
      </div>

      {latest ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between bg-slate-800/50 p-4 rounded-lg">
            <div>
              <p className="text-xs text-slate-400">Latest Decision</p>
              <p className={`text-3xl font-bold ${getDecisionColor(latest.decision)}`}>
                {latest.decision}
              </p>
            </div>
            <div className="text-right">
              <p className="text-xs text-slate-400">Confidence</p>
              <p className="text-xl font-semibold">{(latest.confidence * 100).toFixed(1)}%</p>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3 text-sm">
            <div className="bg-slate-800/30 p-3 rounded">
              <p className="text-xs text-slate-400">Entry</p>
              <p className="font-mono">{latest.entry_price?.toFixed(5) || "-"}</p>
            </div>
            <div className="bg-slate-800/30 p-3 rounded">
              <p className="text-xs text-slate-400">Stop Loss</p>
              <p className="font-mono text-red-400">{latest.stop_loss?.toFixed(5) || "-"}</p>
            </div>
            <div className="bg-slate-800/30 p-3 rounded">
              <p className="text-xs text-slate-400">Take Profit</p>
              <p className="font-mono text-green-400">{latest.take_profit?.toFixed(5) || "-"}</p>
            </div>
          </div>

          <div className="bg-slate-800/30 p-3 rounded">
            <p className="text-xs text-slate-400 mb-1">Rationale</p>
            <p className="text-sm text-slate-300">{latest.rationale || "No rationale provided."}</p>
          </div>

          {latest.risk_reward && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-400">R:R</span>
              <span className="font-semibold">{latest.risk_reward}:1</span>
              <span className="text-slate-400">Size:</span>
              <span className="font-semibold">{latest.position_size_pct}%</span>
            </div>
          )}
        </div>
      ) : (
        <div className="flex items-center gap-2 text-slate-400 py-8">
          <AlertTriangle className="w-5 h-5" />
          <p>No AI decisions yet. Run analysis to begin.</p>
        </div>
      )}
    </div>
  );
}
