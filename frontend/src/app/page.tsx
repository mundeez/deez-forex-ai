"use client";

import { useState, useEffect } from "react";
import { API_URL } from "@/utils/api";
import Header from "@/components/Header";
import ChartPanel from "@/components/ChartPanel";
import MarketInfoBar from "@/components/MarketInfoBar";
import ProfitMetricsPanel from "@/components/ProfitMetricsPanel";
import PositionsPanel from "@/components/PositionsPanel";
import TradeHistoryPanel from "@/components/TradeHistoryPanel";
import AnalysisPanel from "@/components/AnalysisPanel";
import AIDecisionPanel from "@/components/AIDecisionPanel";
import ManualTradePanel from "@/components/ManualTradePanel";
import PairSelector from "@/components/PairSelector";
import ManualOverrideToggle from "@/components/ManualOverrideToggle";
import SuggestionsPanel from "@/components/SuggestionsPanel";
import { useWebSocket } from "@/hooks/useWebSocket";

function getWsUrl(): string {
  if (typeof window === "undefined") return "";
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws`;
}

export default function Home() {
  const [activeSymbol, setActiveSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("1h");
  const [refreshKey, setRefreshKey] = useState(0);
  const [activePairs, setActivePairs] = useState<string[]>(["EURUSD"]);
  const [provider, setProvider] = useState<string>("metaapi");
  const [wsUrl, setWsUrl] = useState<string>("");

  useEffect(() => {
    setWsUrl(getWsUrl());
    // Hydrate provider from backend settings so it persists across reloads
    fetch(`${API_URL}/api/v1/settings`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.data_provider) {
          setProvider(data.data_provider);
        }
      })
      .catch(() => {});
  }, []);

  const { prices, aiDecisions, connected } = useWebSocket(wsUrl, activePairs, provider);

  const livePrice = prices[activeSymbol];

  const handlePairsChange = (pairs: string[]) => {
    setActivePairs(pairs);
    if (pairs.length > 0 && !pairs.includes(activeSymbol)) {
      setActiveSymbol(pairs[0]);
    }
  };

  const handleRefresh = () => setRefreshKey((k) => k + 1);

  return (
    <main className="min-h-screen bg-forex-dark text-slate-200">
      <Header />

      {/* Connection status bar */}
      <div className="max-w-7xl mx-auto px-4 pt-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${connected ? "bg-emerald-500" : "bg-red-500"}`} />
            <span className="text-xs text-slate-400">{connected ? "Live" : "Disconnected"}</span>
          </div>
          <div className="flex items-center gap-3">
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="text-xs bg-slate-800 text-slate-300 border border-slate-600 rounded px-1 py-0.5"
            >
              <option value="metaapi">MetaAPI.cloud</option>
              <option value="mt5_zmq">MT5 Desktop (ZMQ)</option>
            </select>
            <span className="text-xs text-slate-500">
              {activePairs.length} pair{activePairs.length !== 1 ? "s" : ""} active
            </span>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 py-6 grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* LEFT COLUMN */}
        <div className="space-y-4">
          <ProfitMetricsPanel key={`profit-${refreshKey}`} />
          <ManualOverrideToggle />
          <PairSelector onChange={handlePairsChange} />
          <ManualTradePanel symbol={activeSymbol} onTrade={handleRefresh} />
        </div>

        {/* CENTER COLUMN */}
        <div className="lg:col-span-2 space-y-4">
          <MarketInfoBar symbol={activeSymbol} livePrice={livePrice} />

          {/* Timeframe selector */}
          <div className="flex gap-2 flex-wrap">
            {["1m", "5m", "15m", "1h", "4h", "1d"].map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-3 py-1 rounded text-xs font-semibold border transition ${
                  timeframe === tf
                    ? "bg-forex-accent text-white border-forex-accent"
                    : "bg-slate-800 text-slate-300 border-slate-600 hover:bg-slate-700"
                }`}
              >
                {tf}
              </button>
            ))}
          </div>

          {/* Active pair tabs */}
          <div className="flex gap-2">
            {activePairs.map((sym) => (
              <button
                key={sym}
                onClick={() => setActiveSymbol(sym)}
                className={`px-3 py-1.5 rounded-lg text-sm font-semibold border transition ${
                  activeSymbol === sym
                    ? "bg-slate-700 text-white border-slate-500"
                    : "bg-slate-800/50 text-slate-400 border-slate-700 hover:bg-slate-800"
                }`}
              >
                {sym}
                {prices[sym] && (
                  <span className="ml-2 text-xs text-slate-400">
                    {prices[sym].bid.toFixed(5)}
                  </span>
                )}
              </button>
            ))}
          </div>

          <ChartPanel symbol={activeSymbol} timeframe={timeframe} livePrice={livePrice} />

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <AnalysisPanel symbol={activeSymbol} />
            <AIDecisionPanel newDecisions={aiDecisions} />
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div className="space-y-4">
          <SuggestionsPanel />
          <PositionsPanel onRefresh={handleRefresh} />
          <TradeHistoryPanel limit={10} />
        </div>
      </div>
    </main>
  );
}
