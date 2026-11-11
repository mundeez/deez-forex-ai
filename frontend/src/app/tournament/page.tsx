"use client";

import { useState } from "react";
import { API_URL } from "@/utils/api";
import { useFetchOnce, fetchJSON } from "@/hooks/usePolling";

const fmt = (v: any, d = 2) =>
  v === null || v === undefined ? "—" : Number(v).toFixed(d);
const pnl = (v: any) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}$${Number(v).toFixed(2)}`;
const rsum = (v: any) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${Number(v).toFixed(2)}R`;

function PnlCell({ v }: { v: any }) {
  if (v === null || v === undefined) return <td className="py-1 text-right text-slate-500">—</td>;
  return (
    <td className={`py-1 text-right font-mono ${v >= 0 ? "text-emerald-400" : "text-red-400"}`}>
      {pnl(v)}
    </td>
  );
}

function StatsBlock({ s, label }: { s: any; label: string }) {
  if (!s || s.trades === undefined || s.trades === null || s.trades === 0) {
    return (
      <div className="bg-slate-800 rounded-lg p-3 border border-slate-700">
        <p className="text-xs text-slate-500 uppercase mb-1">{label}</p>
        <p className="text-slate-500 text-sm">No trades yet</p>
      </div>
    );
  }
  return (
    <div className="bg-slate-800 rounded-lg p-3 border border-slate-700">
      <p className="text-xs text-slate-500 uppercase mb-2">{label}</p>
      <div className="grid grid-cols-3 gap-x-4 gap-y-1 text-sm">
        <div><span className="text-slate-500">Trades </span><span className="text-slate-200 font-mono">{s.trades}</span></div>
        <div><span className="text-slate-500">WR </span><span className="text-slate-200 font-mono">{s.win_rate !== null ? `${(s.win_rate * 100).toFixed(0)}%` : "—"}</span></div>
        <div><span className="text-slate-500">PF </span><span className="text-slate-200 font-mono">{fmt(s.profit_factor)}</span></div>
        <div><span className="text-slate-500">Net </span><span className={`font-mono ${(s.net_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>{pnl(s.net_pnl)}</span></div>
        <div><span className="text-slate-500">Exp </span><span className="text-slate-200 font-mono">{pnl(s.expectancy)}</span></div>
        <div><span className="text-slate-500">DD </span><span className="text-slate-200 font-mono">{pnl(s.max_drawdown)}</span></div>
        <div><span className="text-slate-500">t </span><span className="text-slate-200 font-mono">{fmt(s.t_stat)}</span></div>
        <div><span className="text-slate-500">PF-CI90 </span><span className="text-slate-200 font-mono">{fmt(s.pf_ci90_low)}</span></div>
      </div>
    </div>
  );
}

export default function TournamentPage() {
  const [variants, setVariants] = useState<any[]>([]);
  const [shadow, setShadow] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<any[]>([]);

  useFetchOnce(async (signal) => {
    const [v, s] = await Promise.all([
      fetchJSON<any[]>(`${API_URL}/api/v1/variants`, signal),
      fetchJSON<any[]>(`${API_URL}/api/v1/variants/shadow`, signal),
    ]);
    if (v) setVariants(v);
    if (s) setShadow(s);
    setLoading(false);
  }, []);

  const loadCandidates = async (variantId: string) => {
    setSelected(variantId);
    const c = await fetchJSON<any[]>(`${API_URL}/api/v1/variants/${variantId}/candidates?limit=30`);
    setCandidates(c || []);
  };

  const shadowMap = Object.fromEntries(shadow.map((s: any) => [s.variant_id, s]));

  if (loading) return <div className="p-8 text-slate-300">Loading tournament…</div>;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold mb-1 text-white">Strategy Tournament</h1>
      <p className="text-sm text-slate-500 mb-6">
        Deterministic candidates → LLM PASS/VETO → $5 fixed risk. Kill: −$40 / neg-expectancy≥30 / PF&lt;1.15≥60.
      </p>

      {/* Variant standings */}
      <div className="bg-slate-800 rounded-xl p-4 border border-slate-700 mb-6">
        <h2 className="text-lg font-semibold mb-3 text-emerald-400">Standings</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 border-b border-slate-700">
                <th className="text-left py-1">Variant</th>
                <th className="text-left py-1">Family</th>
                <th className="text-left py-1">TF</th>
                <th className="text-left py-1">Status</th>
                <th className="text-right py-1">Trades</th>
                <th className="text-right py-1">WR</th>
                <th className="text-right py-1">PF</th>
                <th className="text-right py-1">Net P&L</th>
                <th className="text-right py-1">t-stat</th>
                <th className="text-right py-1">Cand.</th>
                <th className="text-right py-1">Pass%</th>
              </tr>
            </thead>
            <tbody>
              {variants.map((v: any) => {
                const st = v.fx_stats || {};
                const sh = shadowMap[v.variant_id] || {};
                const retired = v.status !== "active";
                return (
                  <tr
                    key={v.variant_id}
                    onClick={() => loadCandidates(v.variant_id)}
                    className={`border-b border-slate-800 cursor-pointer hover:bg-slate-700/40 ${selected === v.variant_id ? "bg-slate-700/60" : ""} ${retired ? "opacity-50" : ""}`}
                  >
                    <td className="py-1 font-mono text-slate-200">{v.variant_id}</td>
                    <td className="py-1 text-slate-400">{v.family}</td>
                    <td className="py-1 text-slate-400">{v.timeframe}</td>
                    <td className="py-1">
                      <span className={`px-1.5 py-0.5 rounded text-xs ${retired ? "bg-red-900/50 text-red-300" : "bg-emerald-900/50 text-emerald-300"}`}>
                        {retired ? `killed${v.kill_reason ? `: ${v.kill_reason}` : ""}` : "live"}
                      </span>
                    </td>
                    <td className="py-1 text-right font-mono text-slate-300">{st.trades ?? 0}</td>
                    <td className="py-1 text-right font-mono text-slate-300">{st.win_rate != null ? `${(st.win_rate * 100).toFixed(0)}%` : "—"}</td>
                    <td className="py-1 text-right font-mono text-slate-300">{fmt(st.profit_factor)}</td>
                    <PnlCell v={st.net_pnl} />
                    <td className="py-1 text-right font-mono text-slate-300">{fmt(st.t_stat)}</td>
                    <td className="py-1 text-right font-mono text-slate-300">{sh.candidates ?? 0}</td>
                    <td className="py-1 text-right font-mono text-slate-300">{sh.pass_rate != null ? `${(sh.pass_rate * 100).toFixed(1)}%` : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Selected variant detail */}
      {selected && (
        <div className="bg-slate-800 rounded-xl p-4 border border-slate-700 mb-6">
          <h2 className="text-lg font-semibold mb-3 text-cyan-400">{selected} — detail</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <StatsBlock s={variants.find((v) => v.variant_id === selected)?.fx_stats} label="FX pairs" />
            <StatsBlock s={variants.find((v) => v.variant_id === selected)?.xauusd_stats} label="XAUUSD" />
          </div>
          <h3 className="text-sm font-semibold text-slate-400 mb-2">Recent candidates</h3>
          <div className="overflow-x-auto max-h-64 overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-700">
                  <th className="text-left py-1">Time</th>
                  <th className="text-left py-1">Symbol</th>
                  <th className="text-left py-1">Dir</th>
                  <th className="text-left py-1">Verdict</th>
                  <th className="text-left py-1">Regime</th>
                  <th className="text-right py-1">Shadow R</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((c: any) => (
                  <tr key={c.id} className="border-b border-slate-800">
                    <td className="py-1 text-slate-400">{c.created_at ? new Date(c.created_at).toLocaleString() : "—"}</td>
                    <td className="py-1 text-slate-300">{c.symbol}</td>
                    <td className="py-1 text-slate-300">{c.direction}</td>
                    <td className={`py-1 font-mono ${c.llm_verdict === "PASS" ? "text-emerald-400" : c.llm_verdict === "VETO" ? "text-amber-400" : "text-slate-500"}`}>
                      {c.llm_verdict || "—"}
                    </td>
                    <td className="py-1 text-slate-400">{c.llm_regime || "—"}</td>
                    <td className={`py-1 text-right font-mono ${(c.shadow_outcome_r ?? 0) > 0 ? "text-emerald-400" : (c.shadow_outcome_r ?? 0) < 0 ? "text-red-400" : "text-slate-500"}`}>
                      {c.shadow_outcome_r != null ? `${c.shadow_outcome_r >= 0 ? "+" : ""}${Number(c.shadow_outcome_r).toFixed(2)}` : "open"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Shadow arm — filter quality */}
      <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
        <h2 className="text-lg font-semibold mb-1 text-amber-400">Shadow arm — is the filter adding value?</h2>
        <p className="text-xs text-slate-500 mb-3">
          R-sum of vetoed/skipped candidates vs what would have traded. Negative veto-R = filter avoided losers (good). Positive veto-R = filter vetoed winners (bad).
        </p>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-slate-400 border-b border-slate-700">
              <th className="text-left py-1">Variant</th>
              <th className="text-right py-1">Candidates</th>
              <th className="text-right py-1">Passed</th>
              <th className="text-right py-1">Vetoed</th>
              <th className="text-right py-1">Resolved</th>
              <th className="text-right py-1">Vetoed R-sum</th>
              <th className="text-right py-1">Passed R-sum</th>
            </tr>
          </thead>
          <tbody>
            {shadow.map((s: any) => (
              <tr key={s.variant_id} className="border-b border-slate-800">
                <td className="py-1 font-mono text-slate-200">{s.variant_id}</td>
                <td className="py-1 text-right font-mono text-slate-300">{s.candidates}</td>
                <td className="py-1 text-right font-mono text-emerald-400">{s.passed}</td>
                <td className="py-1 text-right font-mono text-amber-400">{s.vetoed}</td>
                <td className="py-1 text-right font-mono text-slate-300">{s.resolved}</td>
                <td className={`py-1 text-right font-mono ${s.veto_r_sum < 0 ? "text-emerald-400" : "text-red-400"}`}>{rsum(s.veto_r_sum)}</td>
                <td className={`py-1 text-right font-mono ${s.pass_r_sum > 0 ? "text-emerald-400" : "text-red-400"}`}>{rsum(s.pass_r_sum)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
