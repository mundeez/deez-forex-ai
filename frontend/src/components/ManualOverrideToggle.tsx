"use client";

import { useEffect, useState } from "react";
import { ToggleLeft, ToggleRight, Bot, Hand } from "lucide-react";
import { API_URL } from "@/utils/api";

export default function ManualOverrideToggle() {
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchStatus();
  }, []);

  async function fetchStatus() {
    try {
      const res = await fetch(`${API_URL}/api/v1/manual-override`);
      if (!res.ok) return;
      const data = await res.json();
      setEnabled(data.manual_override);
    } catch (e) {
      console.error("override fetch error", e);
    }
  }

  async function toggle() {
    if (loading) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/manual-override`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (res.ok) {
        const data = await res.json();
        setEnabled(data.manual_override);
      }
    } catch (e) {
      console.error("override toggle error", e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={`rounded-xl border p-4 transition-colors ${
      enabled
        ? "bg-amber-950/30 border-amber-700/50"
        : "bg-emerald-950/30 border-emerald-700/50"
    }`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${enabled ? "bg-amber-900/50" : "bg-emerald-900/50"}`}>
            {enabled ? (
              <Hand className="w-5 h-5 text-amber-400" />
            ) : (
              <Bot className="w-5 h-5 text-emerald-400" />
            )}
          </div>
          <div>
            <h2 className="text-lg font-semibold">{enabled ? "Manual Mode" : "Auto Mode"}</h2>
            <p className="text-xs text-slate-400">
              {enabled
                ? "AI analysis runs but trades require your approval"
                : "AI trades execute automatically based on signals"}
            </p>
          </div>
        </div>
        <button
          onClick={toggle}
          disabled={loading}
          className={`transition ${loading ? "opacity-50" : ""}`}
        >
          {enabled ? (
            <ToggleRight className="w-12 h-12 text-amber-500" />
          ) : (
            <ToggleLeft className="w-12 h-12 text-emerald-500" />
          )}
        </button>
      </div>

      <div className="mt-3 flex gap-2">
        <span className={`text-xs px-2 py-1 rounded-full ${
          enabled ? "bg-amber-900/50 text-amber-300" : "bg-emerald-900/50 text-emerald-300"
        }`}>
          {enabled ? "🟡 Manual Override ON" : "🟢 System Trading"}
        </span>
      </div>
    </div>
  );
}
