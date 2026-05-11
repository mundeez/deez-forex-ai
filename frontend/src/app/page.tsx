"use client";

import { useState, useEffect } from "react";
import Header from "@/components/Header";
import MarketCard from "@/components/MarketCard";
import AIPanel from "@/components/AIPanel";
import TradeJournal from "@/components/TradeJournal";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function Home() {
  const [marketData, setMarketData] = useState<any>(null);
  const [trades, setTrades] = useState<any[]>([]);
  const [aiDecisions, setAiDecisions] = useState<any[]>([]);
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
      const data = await res.json();
      setMarketData(data);
    } catch (e) {
      console.error("market fetch error", e);
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
    try {
      await fetch(`${API_URL}/api/v1/ai/analyze`, { method: "POST" });
      await fetchAiDecisions();
      await fetchTrades();
    } catch (e) {
      console.error("analysis trigger error", e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-forex-dark text-slate-200">
      <Header />
      <div className="max-w-7xl mx-auto px-4 py-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <MarketCard data={marketData} />
          <AIPanel
            decisions={aiDecisions}
            onAnalyze={triggerAnalysis}
            loading={loading}
          />
        </div>
        <div className="space-y-6">
          <TradeJournal trades={trades} />
        </div>
      </div>
    </main>
  );
}
