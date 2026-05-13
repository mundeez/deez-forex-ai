"use client";

import { useEffect, useState } from "react";
import { Activity, Globe, Newspaper, ChevronDown, ChevronUp, BarChart3 } from "lucide-react";
import { API_URL } from "@/utils/api";

interface AnalysisPanelProps {
  symbol: string;
}

export default function AnalysisPanel({ symbol }: AnalysisPanelProps) {
  const [analysis, setAnalysis] = useState<any>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ tech: true, fund: false, sent: false });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchAnalysis();
  }, [symbol]);

  async function fetchAnalysis() {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/analysis/summary?symbol=${symbol}`);
      if (!res.ok) return;
      const data = await res.json();
      setAnalysis(data);
    } catch (e) {
      console.error("analysis fetch error", e);
    } finally {
      setLoading(false);
    }
  }

  const toggle = (key: string) => setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));

  const renderSignal = (label: string, signal: string) => {
    const color = signal === "bullish" ? "text-forex-bullish" : signal === "bearish" ? "text-forex-bearish" : "text-slate-400";
    return (
      <div className="flex justify-between text-sm py-1">
        <span className="text-slate-400">{label}</span>
        <span className={`font-semibold capitalize ${color}`}>{signal || "neutral"}</span>
      </div>
    );
  };

  const combinedSignal = analysis?.combined_signal || "neutral";
  const combinedColor = combinedSignal === "bullish" ? "bg-emerald-900/30 text-emerald-300 border-emerald-700" :
                       combinedSignal === "bearish" ? "bg-red-900/30 text-red-300 border-red-700" :
                       "bg-slate-800 text-slate-400 border-slate-600";

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-forex-accent" />
          <h2 className="text-lg font-semibold">Analysis</h2>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded border ${combinedColor} font-semibold uppercase`}>
          {combinedSignal}
        </span>
      </div>

      {loading && <p className="text-sm text-slate-500">Loading analysis...</p>}

      {/* Technical */}
      <div className="mb-3 border-b border-slate-700 pb-3">
        <button onClick={() => toggle("tech")} className="flex items-center gap-2 w-full text-left">
          <Activity className="w-4 h-4 text-forex-accent" />
          <span className="font-semibold">Technical</span>
          <span className="text-xs ml-2 text-slate-500">{analysis?.technical_signal || "-"}</span>
          {expanded["tech"] ? <ChevronUp className="w-4 h-4 ml-auto" /> : <ChevronDown className="w-4 h-4 ml-auto" />}
        </button>
        {expanded["tech"] && (
          <div className="mt-2 space-y-1 bg-slate-800/30 p-2 rounded text-sm">
            {renderSignal("Overall Signal", analysis?.technical_signal)}
          </div>
        )}
      </div>

      {/* Fundamental */}
      <div className="mb-3 border-b border-slate-700 pb-3">
        <button onClick={() => toggle("fund")} className="flex items-center gap-2 w-full text-left">
          <Globe className="w-4 h-4 text-forex-accent" />
          <span className="font-semibold">Fundamental</span>
          <span className="text-xs ml-2 text-slate-500">{analysis?.fundamental_signal || "-"}</span>
          {expanded["fund"] ? <ChevronUp className="w-4 h-4 ml-auto" /> : <ChevronDown className="w-4 h-4 ml-auto" />}
        </button>
        {expanded["fund"] && (
          <div className="mt-2 space-y-1 bg-slate-800/30 p-2 rounded text-sm">
            {renderSignal("Direction Bias", analysis?.fundamental_signal)}
          </div>
        )}
      </div>

      {/* Sentiment */}
      <div>
        <button onClick={() => toggle("sent")} className="flex items-center gap-2 w-full text-left">
          <Newspaper className="w-4 h-4 text-forex-accent" />
          <span className="font-semibold">Sentiment</span>
          <span className="text-xs ml-2 text-slate-500">{analysis?.sentiment_signal || "-"}</span>
          {expanded["sent"] ? <ChevronUp className="w-4 h-4 ml-auto" /> : <ChevronDown className="w-4 h-4 ml-auto" />}
        </button>
        {expanded["sent"] && (
          <div className="mt-2 space-y-1 bg-slate-800/30 p-2 rounded text-sm">
            {renderSignal("Overall Sentiment", analysis?.sentiment_signal)}
          </div>
        )}
      </div>

      {/* AI Confirmation */}
      {analysis?.ai_decision && (
        <div className="mt-3 pt-3 border-t border-slate-700">
          <p className="text-xs text-slate-400 mb-1">AI Confirmation</p>
          <div className="flex items-center gap-2">
            <span className={`font-semibold text-sm ${
              analysis.ai_decision === "BUY" ? "text-forex-bullish" :
              analysis.ai_decision === "SELL" ? "text-forex-bearish" :
              "text-slate-400"
            }`}>
              {analysis.ai_decision}
            </span>
            {analysis.ai_confidence && (
              <span className="text-xs text-slate-500">
                {(analysis.ai_confidence * 100).toFixed(0)}% confidence
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
