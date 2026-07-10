"use client";

import { useState } from "react";
import { API_URL } from "@/utils/api";
import { useFetchOnce, fetchJSON } from "@/hooks/usePolling";

export default function SystemPage() {
  const [intelligence, setIntelligence] = useState<any>({});
  const [learning, setLearning] = useState<any>({});
  const [loading, setLoading] = useState(true);

  useFetchOnce(async (signal) => {
    const [intelData, learningData] = await Promise.all([
      fetchJSON<any>(`${API_URL}/api/v1/system/intelligence`, signal),
      fetchJSON<any>(`${API_URL}/api/v1/system/learning`, signal),
    ]);
    if (intelData) setIntelligence(intelData);
    if (learningData) setLearning(learningData);
    setLoading(false);
  }, []);

  if (loading) return <div className="p-8 text-slate-300">Loading system intelligence...</div>;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold mb-6 text-white">System Intelligence</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
          <h2 className="text-lg font-semibold mb-3 text-emerald-400">Model Performance</h2>
          {intelligence.model_performance?.length > 0 ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-700">
                  <th className="text-left py-1">Model</th>
                  <th className="text-right py-1">Win Rate</th>
                  <th className="text-right py-1">Avg Return</th>
                  <th className="text-right py-1">Trades</th>
                </tr>
              </thead>
              <tbody>
                {intelligence.model_performance.map((m: any) => (
                  <tr key={m.model_name} className="border-b border-slate-800">
                    <td className="py-1 text-slate-300">{m.model_name}</td>
                    <td className="py-1 text-right text-slate-300">{(m.win_rate * 100).toFixed(1)}%</td>
                    <td className="py-1 text-right text-slate-300">{m.avg_return.toFixed(2)}</td>
                    <td className="py-1 text-right text-slate-300">{m.total_trades}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-slate-500 text-sm">No model performance data yet</p>
          )}
        </div>

        <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
          <h2 className="text-lg font-semibold mb-3 text-blue-400">Entry Gate (XGBoost)</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-400">Blocked (24h)</span>
              <span className="text-white font-mono">{intelligence.entry_gate?.blocked_last_24h || 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Total Decisions (24h)</span>
              <span className="text-white font-mono">{intelligence.entry_gate?.total_last_24h || 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Filter Rate</span>
              <span className="text-white font-mono">{((intelligence.entry_gate?.filter_rate || 0) * 100).toFixed(1)}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Model Loaded</span>
              <span className={intelligence.xgb_model_loaded ? "text-emerald-400" : "text-red-400"}>
                {intelligence.xgb_model_loaded ? "Yes" : "No"}
              </span>
            </div>
          </div>
        </div>

        <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
          <h2 className="text-lg font-semibold mb-3 text-amber-400">Regime Performance (30d)</h2>
          {learning.regime_stats && Object.keys(learning.regime_stats).length > 0 ? (
            <div className="space-y-2">
              {Object.entries(learning.regime_stats).map(([regime, stats]: [string, any]) => (
                <div key={regime} className="flex justify-between text-sm border-b border-slate-800 pb-1">
                  <span className="text-slate-300 capitalize">{regime}</span>
                  <div className="text-right">
                    <span className="text-slate-400">WR: {(stats.win_rate * 100).toFixed(0)}%</span>
                    <span className="text-slate-400 ml-3">PF: {stats.profit_factor}</span>
                    <span className="text-slate-400 ml-3">n={stats.count}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-slate-500 text-sm">No regime data yet</p>
          )}
        </div>

        <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
          <h2 className="text-lg font-semibold mb-3 text-purple-400">Analyst Weights</h2>
          {learning.analyst_weights?.by_regime ? (
            <div className="space-y-3">
              {Object.entries(learning.analyst_weights.by_regime).map(([regime, weights]: [string, any]) => (
                <div key={regime}>
                  <p className="text-xs text-slate-500 uppercase mb-1">{regime}</p>
                  <div className="flex gap-2 text-xs">
                    {Object.entries(weights).map(([k, v]: [string, any]) => (
                      <span key={k} className="bg-slate-700 px-2 py-1 rounded text-slate-300">
                        {k}: {(v * 100).toFixed(0)}%
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-slate-500 text-sm">Weights not computed yet</p>
          )}
        </div>

        <div className="bg-slate-800 rounded-xl p-4 border border-slate-700 md:col-span-2">
          <h2 className="text-lg font-semibold mb-3 text-cyan-400">Backtest Runs</h2>
          {intelligence.backtest_runs?.length > 0 ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-700">
                  <th className="text-left py-1">Type</th>
                  <th className="text-left py-1">Symbol</th>
                  <th className="text-right py-1">Trades</th>
                  <th className="text-right py-1">Win Rate</th>
                  <th className="text-right py-1">PF</th>
                  <th className="text-right py-1">Sharpe</th>
                  <th className="text-right py-1">Max DD</th>
                </tr>
              </thead>
              <tbody>
                {intelligence.backtest_runs.map((b: any) => (
                  <tr key={b.id} className="border-b border-slate-800">
                    <td className="py-1 text-slate-300">{b.backtest_type}</td>
                    <td className="py-1 text-slate-300">{b.symbol}</td>
                    <td className="py-1 text-right text-slate-300">{b.total_trades}</td>
                    <td className="py-1 text-right text-slate-300">{((b.win_rate || 0) * 100).toFixed(1)}%</td>
                    <td className="py-1 text-right text-slate-300">{b.profit_factor}</td>
                    <td className="py-1 text-right text-slate-300">{b.sharpe}</td>
                    <td className="py-1 text-right text-slate-300">{b.max_drawdown}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-slate-500 text-sm">No backtest runs yet</p>
          )}
        </div>
      </div>
    </div>
  );
}
