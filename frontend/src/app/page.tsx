"use client";

import { useState, useEffect } from "react";
import Header from "@/components/Header";
import MarketCard from "@/components/MarketCard";
import AIPanel from "@/components/AIPanel";
import TradeJournal from "@/components/TradeJournal";

const API_URL = "";

export default function Home() {
  const [marketData, setMarketData] = useState<any>(null);
  const [marketError, setMarketError] = useState<string | null>(null);
  const [trades, setTrades] = useState<any[]>([]);
  const [aiDecisions, setAiDecisions] = useState<any[]>([]);
  const [aiError, setAiError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchMarket();
    fetchTrades();
    fetchAiDecisions();
    const interval = setInterval(fetchMarket, 15000);
    return () => clearInterval(interval);
  }, []);

  async function fetchMarket() {
    try {
      const res = await fetch(`${API_URL}/api/v1/market/current`);
      if (!res.ok) {
        const err = await res.text();
        setMarketError(`Backend error (${res.status}): ${err}`);
        return;
      }
      const data = await res.json();
      setMarketData(data);
      setMarketError(null);
    } catch (e: any) {
      console.error("market fetch error", e);
      setMarketError(e.message || "Cannot reach backend. Is it running?");
    }
  }

  async function fetchTrades() {
    try {
      const res = await fetch(`${API_URL}/api/v1/trades?limit=20`);
      const data = await res.json();
      setTrades(data);
    } catch (e) {
      console.error("trades fetch error", e);
    }
  }

  async function fetchAiDecisions() {
    try {
      const res = await fetch(`${API_URL}/api/v1/ai/decisions?limit=10`);
      const data = await res.json();
      setAiDecisions(data);
    } catch (e) {
      console.error("ai decisions fetch error", e);
    }
  }

  async function triggerAnalysis() {
    setLoading(true);
    setAiError(null);
    try {
      const res = await fetch(`${API_URL}/api/v1/ai/analyze`, { method: "POST" });
      if (!res.ok) {
        const err = await res.text();
        setAiError(`Analysis failed (${res.status}): ${err}`);
        return;
      }
      await fetchAiDecisions();
      await fetchTrades();
    } catch (e: any) {
      console.error("analysis trigger error", e);
      setAiError(e.message || "Failed to reach AI service.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-forex-dark text-slate-200">
      <Header />
      <div className="max-w-7xl mx-auto px-4 py-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <MarketCard data={marketData} error={marketError} />
          <AIPanel
            decisions={aiDecisions}
            onAnalyze={triggerAnalysis}
            loading={loading}
            error={aiError}
          />
        </div>
        <div className="space-y-6">
          <TradeJournal trades={trades} />
        </div>
      </div>
    </main>
  );
}
