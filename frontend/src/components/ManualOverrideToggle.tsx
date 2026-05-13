"use client";

import { useEffect, useState } from "react";
import { ToggleLeft, ToggleRight } from "lucide-react";
import { API_URL } from "@/utils/api";

export default function ManualOverrideToggle() {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    fetchStatus();
  }, []);

  async function fetchStatus() {
    try {
      const res = await fetch(`${API_URL}/api/v1/manual-override`);
      if (!res.ok) return;
      const data = await res.json();
      setEnabled(data.enabled);
    } catch (e) {
      console.error("override fetch error", e);
    }
  }

  async function toggle() {
    try {
      const res = await fetch(`${API_URL}/api/v1/manual-override`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !enabled }),
      });
      if (res.ok) {
        const data = await res.json();
        setEnabled(data.enabled);
      }
    } catch (e) {
      console.error("override toggle error", e);
    }
  }

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Manual Override</h2>
          <p className="text-xs text-slate-400">
            {enabled
              ? "AI decisions require manual approval"
              : "AI trades execute automatically"}
          </p>
        </div>
        <button onClick={toggle} className="transition">
          {enabled ? (
            <ToggleRight className="w-10 h-10 text-forex-accent" />
          ) : (
            <ToggleLeft className="w-10 h-10 text-slate-500" />
          )}
        </button>
      </div>
    </div>
  );
}
