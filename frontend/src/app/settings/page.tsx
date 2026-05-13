"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Save, AlertTriangle, Bot, Globe, BarChart3, Shield, Bell } from "lucide-react";
import { API_URL } from "@/utils/api";

interface SettingsData {
  [key: string]: any;
}

const AVAILABLE_PAIRS = [
  "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD"
];

export default function SettingsPage() {
  const router = useRouter();
  const [settings, setSettings] = useState<SettingsData>({});
  const [activePairs, setActivePairs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [activeTab, setActiveTab] = useState("risk");

  useEffect(() => {
    fetchSettings();
    fetchActivePairs();
  }, []);

  async function fetchSettings() {
    try {
      const res = await fetch(`${API_URL}/api/v1/settings`);
      if (!res.ok) return;
      const data = await res.json();
      setSettings(data.settings || data);
    } catch (e) {
      console.error("settings fetch error", e);
    } finally {
      setLoading(false);
    }
  }

  async function fetchActivePairs() {
    try {
      const res = await fetch(`${API_URL}/api/v1/pairs/active`);
      if (!res.ok) return;
      const data = await res.json();
      setActivePairs(data || []);
    } catch (e) {
      console.error("pairs fetch error", e);
    }
  }

  function updateField(key: string, value: any) {
    setSettings((prev) => ({ ...prev, [key]: value }));
  }

  async function saveSettings() {
    setSaving(true);
    setMessage("");
    try {
      const payload: Record<string, any> = {};
      Object.keys(settings).forEach((key) => {
        if (key !== "active_pairs" && key !== "default_pair") {
          payload[key] = settings[key];
        }
      });
      const res = await fetch(`${API_URL}/api/v1/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
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

  async function saveActivePairs() {
    try {
      const res = await fetch(`${API_URL}/api/v1/pairs/active`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(activePairs.map((p, i) => ({
          symbol: p.symbol,
          selection_mode: p.selection_mode || "manual",
          priority: i + 1,
        }))),
      });
      if (res.ok) {
        setMessage("Active pairs updated.");
        fetchActivePairs();
      }
    } catch (e) {
      console.error("save pairs error", e);
    }
  }

  function addPairSlot(symbol: string) {
    if (activePairs.length >= 3) return;
    setActivePairs([...activePairs, { symbol, selection_mode: "manual", priority: activePairs.length + 1 }]);
  }

  function removePairSlot(index: number) {
    setActivePairs(activePairs.filter((_, i) => i !== index));
  }

  function togglePairMode(index: number) {
    setActivePairs(activePairs.map((p, i) =>
      i === index ? { ...p, selection_mode: p.selection_mode === "auto" ? "manual" : "auto" } : p
    ));
  }

  const usedPairs = activePairs.map((p) => p.symbol);
  const availablePairs = AVAILABLE_PAIRS.filter((s) => !usedPairs.includes(s));

  const tabs = [
    { id: "risk", label: "Risk", icon: Shield },
    { id: "pairs", label: "Pairs", icon: Globe },
    { id: "ai", label: "AI", icon: Bot },
    { id: "general", label: "General", icon: BarChart3 },
  ];

  return (
    <main className="min-h-screen bg-forex-dark text-slate-200">
      <div className="max-w-4xl mx-auto px-4 py-6">
        <div className="flex items-center gap-3 mb-6">
          <button onClick={() => router.push("/")} className="text-slate-400 hover:text-white transition">
            <ArrowLeft className="w-5 h-5" />
          </button>
          <h1 className="text-2xl font-bold">Management Console</h1>
        </div>

        {loading ? (
          <p className="text-slate-500">Loading settings...</p>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
            {/* Sidebar tabs */}
            <div className="space-y-2">
              {tabs.map((tab) => {
                const Icon = tab.icon;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg text-left transition ${
                      activeTab === tab.id
                        ? "bg-forex-accent text-white"
                        : "bg-slate-800 text-slate-400 hover:bg-slate-700"
                    }`}
                  >
                    <Icon className="w-5 h-5" />
                    <span className="font-semibold">{tab.label}</span>
                  </button>
                );
              })}
            </div>

            {/* Content */}
            <div className="lg:col-span-3 space-y-6">
              {message && (
                <div className={`text-sm px-4 py-2 rounded-lg ${message.includes("success") || message.includes("updated") ? "bg-emerald-900/30 text-emerald-300" : "bg-red-900/30 text-red-300"}`}>
                  {message}
                </div>
              )}

              {/* Risk Settings */}
              {activeTab === "risk" && (
                <div className="bg-forex-card rounded-xl border border-slate-700 p-6 space-y-6">
                  <div className="flex items-center gap-2 mb-2">
                    <Shield className="w-5 h-5 text-forex-accent" />
                    <h2 className="text-xl font-semibold">Risk Management</h2>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <SettingField
                      label="Max Risk Per Trade (%)"
                      value={settings.max_risk_per_trade_pct}
                      onChange={(v) => updateField("max_risk_per_trade_pct", v)}
                      type="slider"
                      min={0.1}
                      max={10}
                      step={0.1}
                    />
                    <SettingField
                      label="Max Risk Per Trade ($)"
                      value={settings.max_risk_per_trade_abs}
                      onChange={(v) => updateField("max_risk_per_trade_abs", v)}
                      type="number"
                    />
                    <SettingField
                      label="Max Daily Loss (%)"
                      value={settings.max_daily_loss_pct}
                      onChange={(v) => updateField("max_daily_loss_pct", v)}
                      type="slider"
                      min={0.5}
                      max={20}
                      step={0.5}
                    />
                    <SettingField
                      label="Max Open Trades Per Symbol"
                      value={settings.max_open_per_symbol}
                      onChange={(v) => updateField("max_open_per_symbol", v)}
                      type="number"
                    />
                    <SettingField
                      label="Min Risk:Reward Ratio"
                      value={settings.min_risk_reward}
                      onChange={(v) => updateField("min_risk_reward", v)}
                      type="slider"
                      min={0.5}
                      max={5}
                      step={0.1}
                    />
                    <div>
                      <label className="text-sm text-slate-300 block mb-2">Default Trading Mode</label>
                      <div className="flex gap-2">
                        <button
                          onClick={() => updateField("default_mode", "paper")}
                          className={`px-4 py-2 rounded-lg text-sm font-semibold transition ${
                            settings.default_mode === "paper"
                              ? "bg-blue-600 text-white"
                              : "bg-slate-800 text-slate-400 hover:bg-slate-700"
                          }`}
                        >
                          Paper
                        </button>
                        <button
                          onClick={() => updateField("default_mode", "live")}
                          className={`px-4 py-2 rounded-lg text-sm font-semibold transition flex items-center gap-1 ${
                            settings.default_mode === "live"
                              ? "bg-red-600 text-white"
                              : "bg-slate-800 text-slate-400 hover:bg-slate-700"
                          }`}
                        >
                          {settings.default_mode === "live" && <AlertTriangle className="w-4 h-4" />}
                          Live
                        </button>
                      </div>
                    </div>
                  </div>

                  <button
                    onClick={saveSettings}
                    disabled={saving}
                    className="flex items-center gap-2 bg-forex-accent hover:bg-blue-600 text-white px-4 py-2 rounded-lg font-semibold transition disabled:opacity-50"
                  >
                    <Save className="w-4 h-4" />
                    {saving ? "Saving..." : "Save Risk Settings"}
                  </button>
                </div>
              )}

              {/* Pair Settings */}
              {activeTab === "pairs" && (
                <div className="bg-forex-card rounded-xl border border-slate-700 p-6 space-y-6">
                  <div className="flex items-center gap-2 mb-2">
                    <Globe className="w-5 h-5 text-forex-accent" />
                    <h2 className="text-xl font-semibold">Active Pair Configuration</h2>
                  </div>

                  <div className="space-y-3">
                    {activePairs.map((p, idx) => (
                      <div key={idx} className="bg-slate-800/50 p-4 rounded-lg flex items-center justify-between">
                        <div className="flex items-center gap-4">
                          <span className="font-bold text-lg">{p.symbol}</span>
                          <button
                            onClick={() => togglePairMode(idx)}
                            className={`text-xs px-2 py-1 rounded border transition ${
                              p.selection_mode === "auto"
                                ? "border-amber-600 text-amber-400 bg-amber-900/20"
                                : "border-slate-600 text-slate-400"
                            }`}
                          >
                            {p.selection_mode === "auto" ? "Auto-Select" : "Manual"}
                          </button>
                        </div>
                        <button
                          onClick={() => removePairSlot(idx)}
                          className="text-slate-500 hover:text-red-400 transition"
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>

                  {activePairs.length < 3 && availablePairs.length > 0 && (
                    <div>
                      <p className="text-sm text-slate-400 mb-2">Add Pair Slot ({activePairs.length}/3)</p>
                      <div className="grid grid-cols-5 gap-2">
                        {availablePairs.map((sym) => (
                          <button
                            key={sym}
                            onClick={() => addPairSlot(sym)}
                            className="bg-slate-800 hover:bg-slate-700 text-xs py-2 rounded border border-slate-600 transition"
                          >
                            {sym}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  <button
                    onClick={saveActivePairs}
                    className="flex items-center gap-2 bg-forex-accent hover:bg-blue-600 text-white px-4 py-2 rounded-lg font-semibold transition"
                  >
                    <Save className="w-4 h-4" />
                    Save Pair Configuration
                  </button>
                </div>
              )}

              {/* AI Settings */}
              {activeTab === "ai" && (
                <div className="bg-forex-card rounded-xl border border-slate-700 p-6 space-y-6">
                  <div className="flex items-center gap-2 mb-2">
                    <Bot className="w-5 h-5 text-forex-accent" />
                    <h2 className="text-xl font-semibold">AI Configuration</h2>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <SettingField
                      label="AI Confidence Threshold"
                      value={settings.ai_confidence_threshold}
                      onChange={(v) => updateField("ai_confidence_threshold", v)}
                      type="slider"
                      min={0}
                      max={1}
                      step={0.05}
                    />
                    <div>
                      <label className="text-sm text-slate-300 block mb-2">AI Model</label>
                      <select
                        value={settings.ai_model || "claude"}
                        onChange={(e) => updateField("ai_model", e.target.value)}
                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                      >
                        <option value="claude">Claude (Anthropic)</option>
                        <option value="gpt-4o">GPT-4o (OpenAI)</option>
                      </select>
                    </div>
                  </div>

                  <div>
                    <label className="text-sm text-slate-300 block mb-2">Analysis Modules</label>
                    <div className="flex gap-4">
                      {["Technical", "Fundamental", "Sentiment"].map((module) => (
                        <label key={module} className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={settings[`enable_${module.toLowerCase()}`] !== false}
                            onChange={(e) => updateField(`enable_${module.toLowerCase()}`, e.target.checked)}
                            className="w-4 h-4 accent-forex-accent"
                          />
                          <span className="text-sm text-slate-300">{module}</span>
                        </label>
                      ))}
                    </div>
                  </div>

                  <button
                    onClick={saveSettings}
                    disabled={saving}
                    className="flex items-center gap-2 bg-forex-accent hover:bg-blue-600 text-white px-4 py-2 rounded-lg font-semibold transition disabled:opacity-50"
                  >
                    <Save className="w-4 h-4" />
                    {saving ? "Saving..." : "Save AI Settings"}
                  </button>
                </div>
              )}

              {/* General Settings */}
              {activeTab === "general" && (
                <div className="bg-forex-card rounded-xl border border-slate-700 p-6 space-y-6">
                  <div className="flex items-center gap-2 mb-2">
                    <BarChart3 className="w-5 h-5 text-forex-accent" />
                    <h2 className="text-xl font-semibold">General Settings</h2>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                      <label className="text-sm text-slate-300 block mb-2">Equity Balance ($)</label>
                      <input
                        type="number"
                        value={settings.equity_balance || ""}
                        onChange={(e) => updateField("equity_balance", parseFloat(e.target.value))}
                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                      />
                    </div>
                    <div>
                      <label className="text-sm text-slate-300 block mb-2">Chart Update Frequency (ms)</label>
                      <input
                        type="number"
                        value={settings.chart_refresh_ms || 30000}
                        onChange={(e) => updateField("chart_refresh_ms", parseInt(e.target.value))}
                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                      />
                    </div>
                    <div>
                      <label className="text-sm text-slate-300 block mb-2">Analysis Polling Interval (ms)</label>
                      <input
                        type="number"
                        value={settings.analysis_poll_ms || 15000}
                        onChange={(e) => updateField("analysis_poll_ms", parseInt(e.target.value))}
                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="text-sm text-slate-300 block mb-2">Notifications</label>
                    <div className="flex gap-4">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={!!settings.browser_notifications}
                          onChange={(e) => updateField("browser_notifications", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <Bell className="w-4 h-4 text-slate-400" />
                        <span className="text-sm text-slate-300">Browser Notifications</span>
                      </label>
                    </div>
                  </div>

                  <button
                    onClick={saveSettings}
                    disabled={saving}
                    className="flex items-center gap-2 bg-forex-accent hover:bg-blue-600 text-white px-4 py-2 rounded-lg font-semibold transition disabled:opacity-50"
                  >
                    <Save className="w-4 h-4" />
                    {saving ? "Saving..." : "Save General Settings"}
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

function SettingField({
  label,
  value,
  onChange,
  type,
  min,
  max,
  step,
}: {
  label: string;
  value: any;
  onChange: (val: any) => void;
  type: "number" | "slider";
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <div>
      <label className="text-sm text-slate-300 block mb-2">{label}</label>
      {type === "slider" ? (
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={min}
              max={max}
              step={step}
              value={value || 0}
              onChange={(e) => onChange(parseFloat(e.target.value))}
              className="flex-1 accent-forex-accent"
            />
            <input
              type="number"
              min={min}
              max={max}
              step={step}
              value={value || 0}
              onChange={(e) => onChange(parseFloat(e.target.value))}
              className="w-20 bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm text-right"
            />
          </div>
        </div>
      ) : (
        <input
          type="number"
          value={value || ""}
          onChange={(e) => onChange(e.target.value ? parseFloat(e.target.value) : undefined)}
          className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
        />
      )}
    </div>
  );
}
