"use client";

import { useState } from "react";
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

export default function Home() {
  const [activeSymbol, setActiveSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("1h");
  const [refreshKey, setRefreshKey] = useState(0);

  const handlePairsChange = (pairs: string[]) => {
    if (pairs.length > 0 && !pairs.includes(activeSymbol)) {
      setActiveSymbol(pairs[0]);
    }
  };

  const handleRefresh = () => setRefreshKey((k) => k + 1);

  return (
    <main className="min-h-screen bg-forex-dark text-slate-200">
      <Header />
      <div className="max-w-7xl mx-auto px-4 py-6 grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* LEFT SIDEBAR */}
        <div className="space-y-4">
          <ProfitMetricsPanel key={`profit-${refreshKey}`} />
          <ManualOverrideToggle />
          <PairSelector onChange={handlePairsChange} />
          <ManualTradePanel symbol={activeSymbol} onTrade={handleRefresh} />
        </div>

        {/* CENTER */}
        <div className="lg:col-span-2 space-y-4">
          <MarketInfoBar symbol={activeSymbol} />
          <div className="flex gap-2 flex-wrap">
            {["1m", "5m", "15m", "1h", "4h", "1d"].map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-3 py-1 rounded text-xs font-semibold border ${
                  timeframe === tf
                    ? "bg-forex-accent text-white border-forex-accent"
                    : "bg-slate-800 text-slate-300 border-slate-600 hover:bg-slate-700"
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
          <ChartPanel symbol={activeSymbol} timeframe={timeframe} />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <AnalysisPanel symbol={activeSymbol} />
            <AIDecisionPanel />
          </div>
        </div>

        {/* RIGHT SIDEBAR */}
        <div className="space-y-4">
          <PositionsPanel onRefresh={handleRefresh} />
          <TradeHistoryPanel limit={10} />
        </div>
      </div>
    </main>
  );
}
