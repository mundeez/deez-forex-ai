"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { API_URL } from "@/utils/api";
import { fetchJSON } from "@/hooks/usePolling";
import { TradeDetail } from "@/types";
import { formatDateTime, formatDuration, formatPnl } from "@/utils/format";
import { formatSession } from "@/utils/sessions";

export default function TradeDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [detail, setDetail] = useState<TradeDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      const data = await fetchJSON<TradeDetail>(`${API_URL}/api/v1/trades/${id}`);
      if (!cancelled) {
        setDetail(data);
        setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) {
    return <div className="min-h-screen bg-forex-bg flex items-center justify-center text-slate-400">Loading...</div>;
  }

  if (!detail) {
    return (
      <div className="min-h-screen bg-forex-bg flex flex-col items-center justify-center text-slate-400">
        <p>Trade not found.</p>
        <button onClick={() => router.push("/trades")} className="mt-4 text-forex-accent hover:underline">
          Back to trades
        </button>
      </div>
    );
  }

  const t = detail.trade;

  return (
    <div className="min-h-screen bg-forex-bg text-slate-200 p-4 md:p-6">
      <div className="max-w-4xl mx-auto space-y-6">
        <div className="flex items-center gap-3">
          <button onClick={() => router.push("/trades")} className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 transition">
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <h1 className="text-2xl font-bold text-white">Trade #{t.id}</h1>
            <p className="text-sm text-slate-400">
              {t.symbol} · {t.direction.toUpperCase()} · {formatSession(t.session_at_close || t.session_at_open || "")}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Metric label="Status" value={t.status} />
          <Metric label="PnL" value={formatPnl(t.pnl)} valueClass={(t.pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"} />
          <Metric label="PnL %" value={`${(t.pnl_pct ?? 0).toFixed(4)}%`} />
          <Metric label="Entry" value={t.entry_price.toFixed(5)} />
          <Metric label="Exit" value={t.exit_price ? t.exit_price.toFixed(5) : "-"} />
          <Metric label="Duration" value={formatDuration(t.actual_holding_min)} />
          <Metric label="Open Time" value={formatDateTime(t.open_time)} />
          <Metric label="Close Time" value={t.close_time ? formatDateTime(t.close_time) : "-"} />
          <Metric label="Close Reason" value={t.close_reason ?? "-"} />
        </div>

        {detail.ai_decision && (
          <div className="bg-forex-card rounded-xl border border-slate-700 p-6">
            <h2 className="text-lg font-semibold text-white mb-4">AI Decision</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <div><span className="text-slate-500">Decision:</span> <span className="text-white">{detail.ai_decision.decision}</span></div>
              <div><span className="text-slate-500">Confidence:</span> <span className="text-white">{detail.ai_decision.confidence}</span></div>
              <div><span className="text-slate-500">Model:</span> <span className="text-white">{detail.ai_decision.model_used ?? "-"}</span></div>
              <div><span className="text-slate-500">Timestamp:</span> <span className="text-white">{formatDateTime(detail.ai_decision.timestamp)}</span></div>
            </div>
            {detail.ai_decision.rationale && (
              <p className="mt-4 text-sm text-slate-300 whitespace-pre-line">{detail.ai_decision.rationale}</p>
            )}
          </div>
        )}

        <div className="bg-forex-card rounded-xl border border-slate-700 p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Rationale</h2>
          <p className="text-sm text-slate-300 whitespace-pre-line">{t.rationale ?? "No rationale recorded."}</p>
        </div>

        {detail.similar_setups.length > 0 && (
          <div className="bg-forex-card rounded-xl border border-slate-700 p-6">
            <h2 className="text-lg font-semibold text-white mb-4">Similar Past Setups</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-900 text-slate-400">
                  <tr>
                    <th className="text-left px-3 py-2">Symbol</th>
                    <th className="text-left px-3 py-2">Decision</th>
                    <th className="text-right px-3 py-2">Score</th>
                    <th className="text-right px-3 py-2">Confidence</th>
                    <th className="text-right px-3 py-2">Outcome PnL</th>
                    <th className="text-left px-3 py-2">Timestamp</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {detail.similar_setups.map((s) => (
                    <tr key={String(s.id)}>
                      <td className="px-3 py-2 text-white">{s.symbol ?? "-"}</td>
                      <td className="px-3 py-2 text-slate-300">{s.decision ?? "-"}</td>
                      <td className="px-3 py-2 text-right text-slate-300">{s.score.toFixed(3)}</td>
                      <td className="px-3 py-2 text-right text-slate-300">{s.confidence?.toFixed(2) ?? "-"}</td>
                      <td className="px-3 py-2 text-right">
                        <span className={(s.outcome_pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"}>
                          {s.outcome_pnl != null ? formatPnl(s.outcome_pnl) : "-"}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-slate-400">{s.timestamp ? formatDateTime(s.timestamp) : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value, valueClass = "text-white" }: { label: string; value: React.ReactNode; valueClass?: string }) {
  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={`text-sm font-semibold ${valueClass}`}>{value ?? "-"}</div>
    </div>
  );
}
