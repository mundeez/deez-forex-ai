"use client";

import { TrendingUp, TrendingDown } from "lucide-react";

interface MarketCardProps {
  data: any;
  error?: string | null;
}

export default function MarketCard({ data, error }: MarketCardProps) {
  if (error) {
    return (
      <div className="bg-forex-card rounded-xl p-6 border border-red-700">
        <p className="text-red-400 font-medium">Failed to load market data</p>
        <p className="text-red-300 text-sm mt-1">{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-forex-card rounded-xl p-6 border border-slate-700">
        <p className="text-slate-400">Loading market data...</p>
      </div>
    );
  }

  const spread = data.ask && data.bid ? (data.ask - data.bid).toFixed(5) : "-";

  return (
    <div className="bg-forex-card rounded-xl p-6 border border-slate-700">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">EUR/USD</h2>
        <span className="text-xs bg-slate-700 px-2 py-1 rounded">Spot</span>
      </div>
      <div className="grid grid-cols-3 gap-4">
        <div>
          <p className="text-xs text-slate-400">Bid</p>
          <p className="text-2xl font-bold text-forex-bullish">{data.bid}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">Ask</p>
          <p className="text-2xl font-bold text-forex-bearish">{data.ask}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">Spread</p>
          <p className="text-2xl font-bold">{spread}</p>
        </div>
      </div>
    </div>
  );
}
