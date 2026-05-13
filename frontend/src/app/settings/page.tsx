"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Save, AlertTriangle } from "lucide-react";
import { API_URL } from "@/utils/api";

interface SettingsData {
  [key: string]: any;
}

export default function SettingsPage() {
  const router = useRouter();
  const [settings, setSettings] = useState<SettingsData>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetchSettings();
  }, []);

  async function fetchSettings() {
    try {
      const res = await fetch(`${API_URL}/api/v1/settings`);
      if (!res.ok) return;
      const data = await res.json();
      setSettings(data.settings || {});
    } catch (e) {
      console.error("settings fetch error", e);
    } finally {
      setLoading(false);
    }
  }

  function updateField(key: string, value: any) {
    setSettings((prev) => ({ ...prev, [key]: value }));
  }

  async function saveSettings() {
    setSaving(true);
    setMessage("");
    try {
      const res = await fetch(`${API_URL}/api/v1/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings }),
      });
      if (res.ok) {
        setMessage("Settings saved successfully.");
      } else {
        setMessage("Failed to save settings.");
      }
    } catch (e) {
      console.error("save error", e);
      setMessage("Failed to save settings.");
    } finally {
      setSaving(false);
    }
  }

  const sections = [
    {
      title: "Risk Management",
      keys: [
        { key: "max_risk_per_trade_pct", label: "Max Risk Per Trade (%)", type: "number" },
        { key: "max_risk_per_trade_abs", label: "Max Risk Per Trade ($)", type: "number" },
        { key: "max_daily_loss_pct", label: "Max Daily Loss (%)", type: "number" },
        { key: "max_open_per_symbol", label: "Max Open Per Symbol", type: "number" },
      ],
    },
    {
      title: "AI Configuration",
      keys: [
        { key: "ai_confidence_threshold", label: "AI Confidence Threshold", type: "number" },
        { key: "min_risk_reward", label: "Min Risk/Reward", type: "number" },
      ],
    },
    {
      title: "Account",
      keys: [
        { key: "equity_balance", label: "Equity Balance ($)", type: "number" },
      ],
    },
    {
      title: "Notifications",
      keys: [
        { key: "email_alerts", label: "Email Alerts", type: "checkbox" },
        { key: "push_notifications", label: "Push Notifications", type: "checkbox" },
        { key: "alert_email", label: "Alert Email", type: "text" },
      ],
    },
  ];

  return (
    <main className="min-h-screen bg-forex-dark text-slate-200">
      <div className="max-w-3xl mx-auto px-4 py-6">
        <div className="flex items-center gap-3 mb-6">
          <button onClick={() => router.push("/")} className="text-slate-400 hover:text-white">
            <ArrowLeft className="w-5 h-5" />
          </button>
          <h1 className="text-2xl font-bold">Settings</h1>
        </div>

        {loading ? (
          <p className="text-slate-500">Loading settings...</p>
        ) : (
          <div className="space-y-6">
            {sections.map((section) => (
              <div key={section.title} className="bg-forex-card rounded-xl border border-slate-700 p-4">
                <h2 className="text-lg font-semibold mb-3 text-forex-accent">{section.title}</h2>
                <div className="space-y-3">
                  {section.keys.map((field) => (
                    <div key={field.key} className="flex items-center justify-between">
                      <label className="text-sm text-slate-300">{field.label}</label>
                      {field.type === "checkbox" ? (
                        <input
                          type="checkbox"
                          checked={!!settings[field.key]}
                          onChange={(e) => updateField(field.key, e.target.checked)}
                          className="w-5 h-5 accent-forex-accent"
                        />
                      ) : (
                        <input
                          type={field.type}
                          value={settings[field.key] ?? ""}
                          onChange={(e) =>
                            updateField(
                              field.key,
                              field.type === "number" ? parseFloat(e.target.value) : e.target.value
                            )
                          }
                          className="bg-slate-900 border border-slate-600 rounded px-2 py-1 w-40 text-right text-sm"
                        />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}

            {message && (
              <div className={`text-sm ${message.includes("success") ? "text-forex-bullish" : "text-forex-bearish"}`}>
                {message}
              </div>
            )}

            <button
              onClick={saveSettings}
              disabled={saving}
              className="flex items-center gap-2 bg-forex-accent hover:bg-blue-600 text-white px-4 py-2 rounded-lg font-semibold transition disabled:opacity-50"
            >
              <Save className="w-4 h-4" />
              {saving ? "Saving..." : "Save Settings"}
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
