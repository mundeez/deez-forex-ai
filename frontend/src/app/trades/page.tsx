"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Download, Filter, RefreshCw } from "lucide-react";
import { API_URL } from "@/utils/api";
import { fetchJSON } from "@/hooks/usePolling";
import { Trade, TradeListResponse } from "@/types";
import { formatDateTime, formatDuration, formatPnl } from "@/utils/format";
import { formatSession } from "@/utils/sessions";

const OUTCOMES = ["", "win", "loss", "breakeven"];
const SESSIONS = ["", "asian", "london", "ny", "london_ny_overlap", "sydney", "tokyo"];

export default function TradesPage() {
  const router = useRouter();
  const [items, setItems] = useState<Trade[]>([]);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState({
    status: "closed",
    symbol: "",
    session: "",
    outcome: "",
    from_date: "",
    to_date: "",
    min_pnl: "",
    max_pnl: "",
    sort_by: "created_at",
    sort_dir: "desc",
  });

  const buildUrl = (cursor?: number | null) => {
    const params = new URLSearchParams();
    params.set("paginate", "true");
    params.set("limit", "25");
    if (filters.status) params.set("status", filters.status);
    if (filters.symbol) params.set("symbol", filters.symbol.toUpperCase());
    if (filters.session) params.set("session", filters.session);
    if (filters.outcome) params.set("outcome", filters.outcome);
    if (filters.from_date) params.set("from_date", new Date(filters.from_date).toISOString());
    if (filters.to_date) params.set("to_date", new Date(filters.to_date).toISOString());
    if (filters.min_pnl) params.set("min_pnl", filters.min_pnl);
    if (filters.max_pnl) params.set("max_pnl", filters.max_pnl);
    params.set("sort_by", filters.sort_by);
    params.set("sort_dir", filters.sort_dir);
    if (cursor) params.set("cursor", cursor.toString());
    return `${API_URL}/api/v1/trades?${params.toString()}`;
  };

  const load = async (cursor?: number | null) => {
    setLoading(true);
    const data = await fetchJSON<TradeListResponse>(buildUrl(cursor));
    if (data) {
      setItems((prev) => (cursor ? [...prev, ...data.items] : data.items));
      setNextCursor(data.next_cursor);
    }
    setLoading(false);
  };

  useEffect(() => {
    setItems([]);
    load(null);
  }, [filters]);

  const exportCsv = () => {
    if (!items.length) return;
    const header = ["id", "symbol", "direction", "status", "entry_price", "exit_price", "pnl", "pnl_pct", "open_time", "close_time", "close_reason", "session"];
    const rows = items.map((t) => [
      t.id,
      t.symbol,
      t.direction,
      t.status,
      t.entry_price,
      t.exit_price ?? "",
      t.pnl ?? "",
      t.pnl_pct ?? "",
      t.open_time,
      t.close_time ?? "",
      t.close_reason ?? "",
      t.session_at_close ?? "",
    ]);
    const csv = [header, ...rows].map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `trades_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen bg-forex-bg text-slate-200 p-4 md:p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={() => router.push("/")} className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 transition">
              <ArrowLeft className="w-5 h-5" />
            </button>
            <div>
              <h1 className="text-2xl font-bold text-white">Trade History</h1>
              <p className="text-sm text-slate-400">Filterable list of all trades with CSV export</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={exportCsv}
              disabled={!items.length}
              className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-white px-3 py-2 rounded-lg text-sm transition disabled:opacity-50"
            >
              <Download className="w-4 h-4" />
              CSV
            </button>
            <button
              onClick={() => load(null)}
              className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 transition"
            >
              <RefreshCw className={`w-5 h-5 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        <div className="bg-forex-card rounded-xl border border-slate-700 p-4 space-y-4">
          <div className="flex items-center gap-2 text-forex-accent mb-2">
            <Filter className="w-4 h-4" />
            <span className="text-sm font-semibold">Filters</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
            <select
              value={filters.status}
              onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
            >
              <option value="">All statuses</option>
              <option value="open">Open</option>
              <option value="closed">Closed</option>
              <option value="pending">Pending</option>
            </select>
            <input
              type="text"
              placeholder="Symbol (e.g. EURUSD)"
              value={filters.symbol}
              onChange={(e) => setFilters((f) => ({ ...f, symbol: e.target.value }))}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm uppercase"
            />
            <select
              value={filters.session}
              onChange={(e) => setFilters((f) => ({ ...f, session: e.target.value }))}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
            >
              <option value="">All sessions</option>
              {SESSIONS.filter((s) => s).map((s) => (
                <option key={s} value={s}>{formatSession(s)}</option>
              ))}
            </select>
            <select
              value={filters.outcome}
              onChange={(e) => setFilters((f) => ({ ...f, outcome: e.target.value }))}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
            >
              {OUTCOMES.map((o) => (
                <option key={o} value={o}>{o ? o.charAt(0).toUpperCase() + o.slice(1) : "All outcomes"}</option>
              ))}
            </select>
            <input
              type="datetime-local"
              value={filters.from_date}
              onChange={(e) => setFilters((f) => ({ ...f, from_date: e.target.value }))}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
            />
            <input
              type="datetime-local"
              value={filters.to_date}
              onChange={(e) => setFilters((f) => ({ ...f, to_date: e.target.value }))}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
            />
            <input
              type="number"
              placeholder="Min PnL"
              value={filters.min_pnl}
              onChange={(e) => setFilters((f) => ({ ...f, min_pnl: e.target.value }))}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
            />
            <input
              type="number"
              placeholder="Max PnL"
              value={filters.max_pnl}
              onChange={(e) => setFilters((f) => ({ ...f, max_pnl: e.target.value }))}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
            />
          </div>
        </div>

        <div className="bg-forex-card rounded-xl border border-slate-700 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-900 text-slate-400">
                <tr>
                  <th className="text-left px-4 py-3">Symbol</th>
                  <th className="text-left px-4 py-3">Direction</th>
                  <th className="text-left px-4 py-3">Session</th>
                  <th className="text-right px-4 py-3">PnL</th>
                  <th className="text-right px-4 py-3">Entry → Exit</th>
                  <th className="text-left px-4 py-3">Close Reason</th>
                  <th className="text-right px-4 py-3">Duration</th>
                  <th className="text-left px-4 py-3">Close Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {items.map((t) => (
                  <tr
                    key={t.id}
                    onClick={() => router.push(`/trades/${t.id}`)}
                    className="hover:bg-slate-800/50 cursor-pointer transition"
                  >
                    <td className="px-4 py-3 font-medium text-white">{t.symbol}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded text-xs font-semibold ${t.direction === "buy" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}>
                        {t.direction.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-400">{formatSession(t.session_at_close || t.session_at_open || "")}</td>
                    <td className="px-4 py-3 text-right font-semibold">
                      <span className={(t.pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"}>
                        {formatPnl(t.pnl)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-slate-400">
                      {t.entry_price.toFixed(5)} → {t.exit_price ? t.exit_price.toFixed(5) : "-"}
                    </td>
                    <td className="px-4 py-3">
                      {t.close_reason ? (
                        <span className="px-2 py-1 rounded text-xs bg-slate-700 text-slate-300">{t.close_reason}</span>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-400">{formatDuration(t.actual_holding_min)}</td>
                    <td className="px-4 py-3 text-slate-400">{formatDateTime(t.close_time || t.open_time)}</td>
                  </tr>
                ))}
                {items.length === 0 && !loading && (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-slate-500">
                      No trades match the selected filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {nextCursor && (
            <div className="p-4 border-t border-slate-800">
              <button
                onClick={() => load(nextCursor)}
                disabled={loading}
                className="w-full py-2 text-sm font-semibold text-forex-accent hover:text-blue-400 transition disabled:opacity-50"
              >
                Load more
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
