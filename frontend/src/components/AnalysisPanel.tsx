"use client";

import { useEffect, useState } from "react";
import { Activity, Globe, Newspaper, ChevronDown, ChevronUp } from "lucide-react";
import { API_URL } from "@/utils/api";

interface AnalysisPanelProps {
  symbol: string;
}

export default function AnalysisPanel({ symbol }: AnalysisPanelProps) {
  const [analysis, setAnalysis] = useState<any>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    fetchAnalysis();
  }, [symbol]);

  async function fetchAnalysis() {
    try {
      const res = await fetch(`${API_URL}/api/v1/analysis/full?symbol=${symbol}`);
      if (!res.ok) return;
      const data = await res.json();
      setAnalysis(data);
    } catch (e) {
      console.error("analysis fetch error", e);
    }
  }

  const toggle = (key: string) => setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));

  const tech = analysis?.technical;
  const fund = analysis?.fundamental;
  const sent = analysis?.sentiment;

  const renderSignal = (label: string, signal: string) => {
    const color = signal === "bullish" ? "text-forex-bullish" : signal === "bearish" ? "text-forex-bearish" : "text-slate-400";
    return (
      <div className="flex justify-between text-sm py-1">
        <span className="text-slate-400">{label}</span>
        <span className={`font-semibold capitalize ${color}`}>{signal || "neutral"}</span>
      </div>
    );
  };

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <h2 className="text-lg font-semibold mb-3">Multi-Factor Analysis</h2>

      {/* Technical */}
      <div className="mb-3 border-b border-slate-700 pb-3">
        <button onClick={() => toggle("tech")} className="flex items-center gap-2 w-full text-left">
          <Activity className="w-4 h-4 text-forex-accent" />
          <span className="font-semibold">Technical</span>
          {expanded["tech"] ? <ChevronUp className="w-4 h-4 ml-auto" /> : <ChevronDown className="w-4 h-4 ml-auto" />}
        </button>
        {renderSignal("Overall", tech?.overall_signal)}
        {expanded["tech"] && tech?.timeframes && (
          <div className="mt-2 space-y-1 bg-slate-800/30 p-2 rounded">
            {Object.entries(tech.timeframes).map(([tf, val]: [string, any]) => (
              <div key={tf}>
                <p className="text-xs font-semibold text-slate-300">{tf}</p>
                {renderSignal("Signal", val.signal)}
                {val.ema_signal && renderSignal("EMA", val.ema_signal)}
                {val.rsi_value !== undefined && (
                  <div className="flex justify-between text-xs py-0.5">
                    <span className="text-slate-500">RSI</span>
                    <span>{val.rsi_value.toFixed(1)}</span>
                  </div>
                )}
                {val.macd_signal && renderSignal("MACD", val.macd_signal)}
                {val.bb_signal && renderSignal("BB", val.bb_signal)}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Fundamental */}
      <div className="mb-3 border-b border-slate-700 pb-3">
        <button onClick={() => toggle("fund")} className="flex items-center gap-2 w-full text-left">
          <Globe className="w-4 h-4 text-forex-accent" />
          <span className="font-semibold">Fundamental</span>
          {expanded["fund"] ? <ChevronUp className="w-4 h-4 ml-auto" /> : <ChevronDown className="w-4 h-4 ml-auto" />}
        </button>
        {renderSignal("Direction", fund?.direction_bias)}
        {expanded["fund"] && (
          <div className="mt-2 space-y-1 bg-slate-800/30 p-2 rounded text-sm">
            <div className="flex justify-between"><span className="text-slate-500">Event Risk</span><span>{fund?.event_risk || "-"}</span></div>
            <div className="flex justify-between"><span className="text-slate-500">Rate Spread</span><span>{fund?.rate_spread || "-"}</span></div>
            {fund?.news_headlines && (
              <div className="mt-1">
                <p className="text-xs text-slate-500">Headlines</p>
                <ul className="list-disc list-inside text-xs text-slate-300">
                  {fund.news_headlines.slice(0, 3).map((h: string, i: number) => (
                    <li key={i}>{h}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Sentiment */}
      <div>
        <button onClick={() => toggle("sent")} className="flex items-center gap-2 w-full text-left">
          <Newspaper className="w-4 h-4 text-forex-accent" />
          <span className="font-semibold">Sentiment</span>
          {expanded["sent"] ? <ChevronUp className="w-4 h-4 ml-auto" /> : <ChevronDown className="w-4 h-4 ml-auto" />}
        </button>
        {renderSignal("Overall", sent?.overall_sentiment)}
        {expanded["sent"] && (
          <div className="mt-2 space-y-1 bg-slate-800/30 p-2 rounded text-sm">
            {sent?.retail_sentiment && renderSignal("Retail", sent.retail_sentiment)}
            {sent?.institutional_bias && renderSignal("Institutional", sent.institutional_bias)}
            {sent?.news_sentiment && renderSignal("News", sent.news_sentiment)}
          </div>
        )}
      </div>
    </div>
  );
}
