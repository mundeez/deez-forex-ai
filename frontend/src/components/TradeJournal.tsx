"use client";

import { BookOpen } from "lucide-react";

interface TradeJournalProps {
  trades: any[];
}

export default function TradeJournal({ trades }: TradeJournalProps) {
  return (
    <div className="bg-forex-card rounded-xl p-6 border border-slate-700">
      <div className="flex items-center gap-2 mb-4">
        <BookOpen className="w-5 h-5 text-forex-accent" />
        <h2 className="text-lg font-semibold">Trade Journal</h2>
      </div>

      <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
        {trades.length === 0 && (
          <p className="text-slate-400 text-sm">No trades recorded yet.</p>
        )}
        {trades.map((t: any) => (
          <div
            key={t.id}
            className="flex items-center justify-between bg-slate-800/40 p-3 rounded-lg text-sm"
          >
            <div className="flex items-center gap-3">
              <span
                className={`text-xs font-bold px-2 py-0.5 rounded ${
                  t.direction === "buy"
                    ? "bg-green-500/20 text-green-400"
                    : "bg-red-500/20 text-red-400"
                }`}
              >
                {t.direction.toUpperCase()}
              </span>
              <div>
                <p className="font-medium">{t.symbol}</p>
                <p className="text-xs text-slate-400">
                  {new Date(t.created_at).toLocaleString()}
                </p>
              </div>
            </div>
            <div className="text-right">
              {t.pnl !== null ? (
                <p className={t.pnl >= 0 ? "text-green-400" : "text-red-400"}>
                  {t.pnl >= 0 ? "+" : ""}
                  {t.pnl.toFixed(2)}
                </p>
              ) : (
                <span className="text-xs bg-slate-600 px-2 py-0.5 rounded">{t.status}</span>
              )}
              <p className="text-xs text-slate-400">{t.mode}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
