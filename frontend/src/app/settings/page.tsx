"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Save, AlertTriangle, Bot, Globe, BarChart3, Shield, Bell, Zap, Clock } from "lucide-react";
import { API_URL } from "@/utils/api";

interface SettingsData {
  [key: string]: any;
}

const AVAILABLE_PAIRS = [
  "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD"
];

const AI_MODELS: Record<string, { label: string; description: string }> = {
  // --- Free tier (verified against live OpenRouter catalogue) ---
  "nvidia/nemotron-3-super-120b-a12b:free": {
    label: "NVIDIA Nemotron Super 120B (Free)",
    description: "Zero cost. NVIDIA's 120B parameter model. Strong reasoning, good JSON output. Default in rotation pool.",
  },
  "deepseek/deepseek-v4-flash:free": {
    label: "DeepSeek V4 Flash (Free)",
    description: "Zero cost. DeepSeek's latest fast model. Excellent numerical reasoning. May be rate-limited at peak times.",
  },
  "qwen/qwen3-next-80b-a3b-instruct:free": {
    label: "Qwen3 Next 80B (Free)",
    description: "Zero cost. Alibaba's latest reasoning model. Strong multi-step reasoning and JSON adherence.",
  },
  "meta-llama/llama-3.3-70b-instruct:free": {
    label: "Llama 3.3 70B Instruct (Free)",
    description: "Zero cost. Meta's flagship open model. Good general reasoning and instruction following.",
  },
  "openai/gpt-oss-120b:free": {
    label: "GPT-OSS 120B (Free)",
    description: "Zero cost. OpenAI's open-weight model. Good structured output and reasoning.",
  },
  "z-ai/glm-4.5-air:free": {
    label: "GLM-4.5 Air (Free)",
    description: "Zero cost. Zhipu AI's lightweight model. Good balance of speed and accuracy.",
  },
  "moonshotai/kimi-k2.6:free": {
    label: "Moonshot Kimi K2.6 (Free)",
    description: "Zero cost. Moonshot AI's long-context model. Strong at long-horizon reasoning.",
  },
  "qwen/qwen3-coder:free": {
    label: "Qwen3 Coder (Free)",
    description: "Zero cost. Alibaba's code-specialised model. Excellent at structured JSON parsing.",
  },
  "nvidia/nemotron-3-nano-30b-a3b:free": {
    label: "NVIDIA Nemotron Nano 30B (Free)",
    description: "Zero cost. NVIDIA's smaller model. Faster responses, good for high-frequency rotation.",
  },
  "nvidia/nemotron-3-12b-a3b:free": {
    label: "NVIDIA Nemotron 12B (Free)",
    description: "Zero cost. NVIDIA's compact model. Very fast, useful as a cooldown backup.",
  },
  "deepseek/deepseek-v3-0324:free": {
    label: "DeepSeek V3 0324 (Free)",
    description: "Zero cost. DeepSeek V3 base model. Strong numerical and analytical reasoning.",
  },
  "deepseek/deepseek-r1:free": {
    label: "DeepSeek R1 (Free)",
    description: "Zero cost. DeepSeek's reasoning model. Chain-of-thought style, slower but thorough.",
  },
  "meta-llama/llama-4-scout-17b-16e-instruct:free": {
    label: "Llama 4 Scout 17B (Free)",
    description: "Zero cost. Meta's newer small model. Fast and efficient for lightweight tasks.",
  },
  "microsoft/phi-4-reasoning-plus:free": {
    label: "Phi-4 Reasoning Plus (Free)",
    description: "Zero cost. Microsoft's reasoning variant. Good at step-by-step analysis.",
  },
  "microsoft/phi-4-reasoning:free": {
    label: "Phi-4 Reasoning (Free)",
    description: "Zero cost. Microsoft's base reasoning model. Solid analytical capability.",
  },
  "microsoft/phi-4-multimodal-instruct:free": {
    label: "Phi-4 Multimodal (Free)",
    description: "Zero cost. Microsoft's multimodal variant. Can process chart images if enabled.",
  },
  "google/gemini-2.5-flash-preview:free": {
    label: "Gemini 2.5 Flash Preview (Free)",
    description: "Zero cost. Google's flash preview. Very fast with good JSON mode reliability.",
  },
  "google/gemini-2.5-pro-preview:free": {
    label: "Gemini 2.5 Pro Preview (Free)",
    description: "Zero cost. Google's pro preview. Highest quality free model, may be heavily rate-limited.",
  },
  "openai/gpt-4.1-nano:free": {
    label: "GPT-4.1 Nano (Free)",
    description: "Zero cost. OpenAI's smallest model. Ultra-fast, best for cooldown rotation backup.",
  },
  "openai/gpt-4.1-mini:free": {
    label: "GPT-4.1 Mini (Free)",
    description: "Zero cost. OpenAI's mini model. Fast and reliable structured output.",
  },
  "anthropic/claude-sonnet-4-20250514:free": {
    label: "Claude Sonnet 4 (Free)",
    description: "Zero cost. Anthropic's Sonnet 4 preview. Excellent reasoning, strict rate limits.",
  },
  "perplexity/sonar-reasoning:free": {
    label: "Perplexity Sonar Reasoning (Free)",
    description: "Zero cost. Perplexity's reasoning model. Good at evidence-based conclusions.",
  },
  "perplexity/sonar:free": {
    label: "Perplexity Sonar (Free)",
    description: "Zero cost. Perplexity's base model. Fast web-aware responses.",
  },
  "thudm/glm-4.5-air:free": {
    label: "THUDM GLM-4.5 Air (Free)",
    description: "Zero cost. THUDM's GLM variant. Good general reasoning, low latency.",
  },
  "thudm/glm-4.5-9b:free": {
    label: "THUDM GLM-4.5 9B (Free)",
    description: "Zero cost. THUDM's 9B parameter model. Very fast, good for high-frequency rotation.",
  },
  "google/gemma-4-26b-a4b-it:free": {
    label: "Gemma 4 26B (Free)",
    description: "Zero cost. Google's latest open model. Good general reasoning. May be rate-limited.",
  },
  // --- Paid tier (requires funded OpenRouter key) ---
  "google/gemini-2.5-flash": {
    label: "Gemini 2.5 Flash (Paid)",
    description: "~$0.15/M tokens. Best JSON mode on OpenRouter. Very fast, reliable. Requires funded key. Default paid fallback.",
  },
  "deepseek/deepseek-chat": {
    label: "DeepSeek V3 (Paid)",
    description: "~$0.28/M tokens. Excellent numerical reasoning. Extremely cheap. Requires funded key.",
  },
  "openai/gpt-4o-mini": {
    label: "GPT-4o Mini (Paid)",
    description: "~$0.15/M tokens. Very reliable JSON output. Requires funded key.",
  },
  "anthropic/claude-sonnet-4.5": {
    label: "Claude Sonnet 4.5 (Paid)",
    description: "Excellent reasoning but expensive. Previously the default. Requires funded OpenRouter account.",
  },
  "deepseek/deepseek-v4-flash": {
    label: "DeepSeek V4 Flash (Paid)",
    description: "~$0.10/M tokens. Extreme throughput. Perfect for multi-pair scanning.",
  },
  "meta-llama/llama-3.3-70b-instruct": {
    label: "Llama 3.3 70B (Paid)",
    description: "~$0.20/M tokens. High-quality open model. Great for sentiment and fundamental analysis.",
  },
  "deepseek/deepseek-r1": {
    label: "DeepSeek R1 (Paid)",
    description: "~$0.70/M input. Reasoning model with chain-of-thought. Best verifier / risk manager.",
  },
  "openai/gpt-4o": {
    label: "GPT-4o (Paid)",
    description: "~$2.50/M tokens. Frontier model. Best technical analysis accuracy.",
  },
  "anthropic/claude-opus-4.1": {
    label: "Claude Opus 4.1 (Paid)",
    description: "~$15/M tokens. Top-tier reasoning. Best lead strategist for extreme mode.",
  },
  "openai/o3": {
    label: "OpenAI o3 (Paid)",
    description: "~$10/M tokens. Advanced reasoning. Best macro / cross-market correlation analysis.",
  },
};
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
    { id: "trading", label: "Trading", icon: Zap },
    { id: "risk", label: "Risk", icon: Shield },
    { id: "pairs", label: "Pairs", icon: Globe },
    { id: "ai", label: "AI", icon: Bot },
    { id: "notifications", label: "Notifications", icon: Bell },
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

              {/* Trading Settings */}
              {activeTab === "trading" && (
                <div className="bg-forex-card rounded-xl border border-slate-700 p-6 space-y-6">
                  <div className="flex items-center gap-2 mb-2">
                    <Zap className="w-5 h-5 text-forex-accent" />
                    <h2 className="text-xl font-semibold">Trading Strategy</h2>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                      <label className="text-sm text-slate-300 block mb-2">Strategy Mode</label>
                      <div className="flex gap-2">
                        {["scalping", "day_trading", "swing"].map((mode) => (
                          <button
                            key={mode}
                            onClick={() => updateField("strategy_mode", mode)}
                            className={`px-4 py-2 rounded-lg text-sm font-semibold transition ${
                              settings.strategy_mode === mode
                                ? "bg-forex-accent text-white"
                                : "bg-slate-800 text-slate-400 hover:bg-slate-700"
                            }`}
                          >
                            {mode === "scalping" ? "Scalping" : mode === "day_trading" ? "Day Trading" : "Swing"}
                          </button>
                        ))}
                      </div>
                      <p className="text-xs text-slate-500 mt-2">
                        {settings.strategy_mode === "scalping"
                          ? "Fast trades (1-15 min). Analyzes 1m/5m/15m. Tight stops. Max 10 min hold."
                          : settings.strategy_mode === "day_trading"
                          ? "Intraday trades (15 min - 4 hrs). Analyzes 5m/15m/1h. Medium stops. Max 2 hr hold."
                          : "Longer holds (4+ hrs). Analyzes 1h/4h/1D. Wide stops. No time limit."}
                      </p>
                    </div>

                    <div>
                      <label className="text-sm text-slate-300 block mb-2">Data Provider</label>
                      <div className="flex gap-2">
                        {["mt5_zmq", "metaapi"].map((provider) => (
                          <button
                            key={provider}
                            onClick={() => updateField("data_provider", provider)}
                            className={`px-4 py-2 rounded-lg text-sm font-semibold transition ${
                              settings.data_provider === provider
                                ? "bg-forex-accent text-white"
                                : "bg-slate-800 text-slate-400 hover:bg-slate-700"
                            }`}
                          >
                            {provider === "mt5_zmq" ? "MT5 ZMQ" : "MetaAPI"}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div>
                      <label className="text-sm text-slate-300 block mb-2">Equity Balance ($)</label>
                      <input
                        type="number"
                        value={settings.equity_balance || 100}
                        onChange={(e) => updateField("equity_balance", parseFloat(e.target.value))}
                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                      />
                      <p className="text-xs text-slate-500 mt-1">Current account balance for position sizing</p>
                    </div>

                    <div>
                      <label className="text-sm text-slate-300 block mb-2">Max Trade Duration (minutes)</label>
                      <input
                        type="number"
                        value={settings.max_trade_duration_min || 10}
                        onChange={(e) => updateField("max_trade_duration_min", parseInt(e.target.value))}
                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                      />
                      <p className="text-xs text-slate-500 mt-1">Auto-close trades after this many minutes</p>
                    </div>
                  </div>

                  {/* Trailing Stop & Partial Profits */}
                  <div className="border-t border-slate-700 pt-4">
                    <h3 className="text-lg font-semibold mb-4 text-slate-200">Trailing Stop & Partial Profits</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={settings.trailing_stop_enabled !== false}
                          onChange={(e) => updateField("trailing_stop_enabled", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <div>
                          <span className="text-sm text-slate-300">Trailing Stop</span>
                          <p className="text-xs text-slate-500">Moves SL to breakeven at 1x ATR, then trails by ATR distance</p>
                        </div>
                      </div>
                      <div>
                        <label className="text-sm text-slate-300 block mb-1">Trailing Stop Distance (x ATR)</label>
                        <input
                          type="number"
                          step="0.1"
                          value={settings.trailing_stop_distance_atr || 1.0}
                          onChange={(e) => updateField("trailing_stop_distance_atr", parseFloat(e.target.value))}
                          className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                        />
                      </div>
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={settings.partial_profit_enabled !== false}
                          onChange={(e) => updateField("partial_profit_enabled", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <div>
                          <span className="text-sm text-slate-300">Partial Profit Taking</span>
                          <p className="text-xs text-slate-500">Close 50% at 1R profit, move SL to breakeven</p>
                        </div>
                      </div>
                      <div>
                        <label className="text-sm text-slate-300 block mb-1">Partial Profit % to Close</label>
                        <input
                          type="number"
                          value={settings.partial_profit_pct || 50}
                          onChange={(e) => updateField("partial_profit_pct", parseFloat(e.target.value))}
                          className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Spread & Drawdown Guards */}
                  <div className="border-t border-slate-700 pt-4">
                    <h3 className="text-lg font-semibold mb-4 text-slate-200">Filters & Guards</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={settings.spread_filter_enabled !== false}
                          onChange={(e) => updateField("spread_filter_enabled", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <div>
                          <span className="text-sm text-slate-300">Spread Filter</span>
                          <p className="text-xs text-slate-500">Skip trades when spread &gt; 30% of ATR</p>
                        </div>
                      </div>
                      <div>
                        <label className="text-sm text-slate-300 block mb-1">Max Spread / ATR Ratio</label>
                        <input
                          type="number"
                          step="0.05"
                          value={settings.max_spread_to_atr_ratio || 0.30}
                          onChange={(e) => updateField("max_spread_to_atr_ratio", parseFloat(e.target.value))}
                          className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                        />
                      </div>
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={settings.drawdown_guard_enabled !== false}
                          onChange={(e) => updateField("drawdown_guard_enabled", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <div>
                          <span className="text-sm text-slate-300">Drawdown Guard</span>
                          <p className="text-xs text-slate-500">Reduce position size during losing streaks</p>
                        </div>
                      </div>
                      <div>
                        <label className="text-sm text-slate-300 block mb-1">Correlation Guard</label>
                        <div className="flex items-center gap-3">
                          <input
                            type="checkbox"
                            checked={settings.correlation_guard_enabled !== false}
                            onChange={(e) => updateField("correlation_guard_enabled", e.target.checked)}
                            className="w-4 h-4 accent-forex-accent"
                          />
                          <span className="text-sm text-slate-300">Block correlated pairs</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* News Halt */}
                  <div className="border-t border-slate-700 pt-4">
                    <h3 className="text-lg font-semibold mb-4 text-slate-200">News-Based Trading Halt</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={settings.news_halt_enabled !== false}
                          onChange={(e) => updateField("news_halt_enabled", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <div>
                          <span className="text-sm text-slate-300">Pause trading around high-impact news</span>
                          <p className="text-xs text-slate-500">Uses free ForexFactory calendar (FOMC, NFP, CPI, etc.)</p>
                        </div>
                      </div>
                      <div>
                        <label className="text-sm text-slate-300 block mb-1">Buffer Before Event (min)</label>
                        <input
                          type="number"
                          value={settings.news_halt_buffer_before_min || 15}
                          onChange={(e) => updateField("news_halt_buffer_before_min", parseInt(e.target.value))}
                          className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                        />
                      </div>
                      <div>
                        <label className="text-sm text-slate-300 block mb-1">Buffer After Event (min)</label>
                        <input
                          type="number"
                          value={settings.news_halt_buffer_after_min || 30}
                          onChange={(e) => updateField("news_halt_buffer_after_min", parseInt(e.target.value))}
                          className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                        />
                      </div>
                    </div>
                  </div>

                  <div className="border-t border-slate-700 pt-4">
                    <div className="flex items-center gap-2 mb-4">
                      <Clock className="w-5 h-5 text-forex-accent" />
                      <h3 className="text-lg font-semibold">End of Day / Weekend Closure</h3>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={settings.eod_close_enabled !== false}
                          onChange={(e) => updateField("eod_close_enabled", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <div>
                          <span className="text-sm text-slate-300">Close all trades before EOD</span>
                          <p className="text-xs text-slate-500">Closes all positions at 21:30 UTC Mon-Fri</p>
                        </div>
                      </div>
                      <div>
                        <label className="text-sm text-slate-300 block mb-1">No New Entries Before (UTC)</label>
                        <input
                          type="time"
                          value={settings.eod_no_new_entries_before || "21:00"}
                          onChange={(e) => updateField("eod_no_new_entries_before", e.target.value)}
                          className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                        />
                      </div>
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={settings.weekend_close_enabled !== false}
                          onChange={(e) => updateField("weekend_close_enabled", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <div>
                          <span className="text-sm text-slate-300">Close before weekend</span>
                          <p className="text-xs text-slate-500">Closes all positions Friday 21:00 UTC</p>
                        </div>
                      </div>
                      <div>
                        <label className="text-sm text-slate-300 block mb-1">Weekend Resume (UTC Sunday)</label>
                        <input
                          type="time"
                          value={settings.weekend_resume_time_utc || "22:00"}
                          onChange={(e) => updateField("weekend_resume_time_utc", e.target.value)}
                          className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                        />
                      </div>
                    </div>
                  </div>

                  <button
                    onClick={saveSettings}
                    disabled={saving}
                    className="flex items-center gap-2 bg-forex-accent hover:bg-blue-600 text-white px-4 py-2 rounded-lg font-semibold transition disabled:opacity-50"
                  >
                    <Save className="w-4 h-4" />
                    {saving ? "Saving..." : "Save Trading Settings"}
                  </button>
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
                        value={settings.ai_model || "nvidia/nemotron-3-super-120b-a12b:free"}
                        onChange={(e) => updateField("ai_model", e.target.value)}
                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm cursor-pointer"
                        title={AI_MODELS[settings.ai_model]?.description || ""}
                      >
                        {Object.entries(AI_MODELS).map(([id, { label }]) => (
                          <option key={id} value={id} title={AI_MODELS[id]?.description}>
                            {label}
                          </option>
                        ))}
                      </select>
                      {/* Tooltip description for currently selected model */}
                      {settings.ai_model && AI_MODELS[settings.ai_model] && (
                        <p className="text-xs text-slate-500 mt-1.5 leading-relaxed">
                          {AI_MODELS[settings.ai_model].description}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Model Rotation */}
                  <div className="border-t border-slate-700 pt-4">
                    <h3 className="text-lg font-semibold mb-4 text-slate-200">Model Rotation (Free-Tier Load Balancing)</h3>
                    <p className="text-xs text-slate-500 mb-4">
                      Distribute AI calls across multiple free models to avoid per-model rate limits.
                      When one model hits a quota, the system automatically fails over to the next.
                    </p>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={settings.ai_model_rotation_enabled !== false}
                          onChange={(e) => updateField("ai_model_rotation_enabled", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <div>
                          <span className="text-sm text-slate-300">Enable Model Rotation</span>
                          <p className="text-xs text-slate-500">Round-robin across the pool below. Disabling locks to the selected AI Model only.</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={settings.ai_paid_fallback_enabled === true}
                          onChange={(e) => updateField("ai_paid_fallback_enabled", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <div>
                          <span className="text-sm text-slate-300">Allow Paid Fallback</span>
                          <p className="text-xs text-slate-500">When every free model is cooling down, use a paid model (requires funded key).</p>
                        </div>
                      </div>
                      {settings.ai_paid_fallback_enabled && (
                        <div>
                          <label className="text-sm text-slate-300 block mb-2">Paid Fallback Model</label>
                          <select
                            value={settings.ai_paid_fallback_model || "google/gemini-2.5-flash"}
                            onChange={(e) => updateField("ai_paid_fallback_model", e.target.value)}
                            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                          >
                            {Object.entries(AI_MODELS)
                              .filter(([id]) => !id.endsWith(":free"))
                              .map(([id, { label }]) => (
                                <option key={id} value={id}>{label}</option>
                              ))}
                          </select>
                        </div>
                      )}
                      <div>
                        <label className="text-sm text-slate-300 block mb-2">Cooldown Seconds</label>
                        <input
                          type="number"
                          min={10}
                          max={3600}
                          value={settings.ai_model_cooldown_sec || 120}
                          onChange={(e) => updateField("ai_model_cooldown_sec", parseInt(e.target.value, 10))}
                          className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                        />
                        <p className="text-xs text-slate-500 mt-1">How long a model is skipped after a rate-limit error (10-3600s).</p>
                      </div>
                    </div>
                    <div className="mt-4">
                      <label className="text-sm text-slate-300 block mb-2">Rotation Pool (comma-separated model IDs)</label>
                      <textarea
                        value={settings.ai_model_pool || ""}
                        onChange={(e) => updateField("ai_model_pool", e.target.value)}
                        rows={4}
                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm font-mono"
                        placeholder="nvidia/nemotron-3-super-120b-a12b:free,deepseek/deepseek-v4-flash:free,..."
                      />
                      <p className="text-xs text-slate-500 mt-1.5">
                        Only models ending in <code>:free</code> are used in the free rotation. Paid models are only used as the fallback above.
                      </p>
                    </div>
                  </div>

                  {/* Fallback Strategy */}
                  <div className="border-t border-slate-700 pt-4">
                    <h3 className="text-lg font-semibold mb-4 text-slate-200">AI Failure Handling</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div>
                        <label className="text-sm text-slate-300 block mb-2">Fallback Strategy</label>
                        <select
                          value={settings.ai_fallback_strategy || "hold"}
                          onChange={(e) => updateField("ai_fallback_strategy", e.target.value)}
                          className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                        >
                          <option value="hold">Hold All (Safe)</option>
                          <option value="rule_based">Rule-Based Technical</option>
                          <option value="pause_and_alert">Pause & Alert</option>
                        </select>
                        <p className="text-xs text-slate-500 mt-1.5">
                          {settings.ai_fallback_strategy === "rule_based"
                            ? "Use EMA crossover + ADX + RSI rules when AI is down. May produce lower quality signals."
                            : settings.ai_fallback_strategy === "pause_and_alert"
                            ? "Stop all trading and send alert when AI is unavailable. Safest option."
                            : "Return HOLD for all pairs. No trades will be placed until AI recovers."}
                        </p>
                      </div>
                      <div>
                        <label className="text-sm text-slate-300 block mb-2">Trade Aggressiveness</label>
                        <div className="flex gap-2">
                          {["conservative", "moderate", "aggressive"].map((level) => (
                            <button
                              key={level}
                              onClick={() => updateField("trade_aggressiveness", level)}
                              className={`px-4 py-2 rounded-lg text-sm font-semibold transition capitalize ${
                                (settings.trade_aggressiveness || "moderate") === level
                                  ? level === "aggressive"
                                    ? "bg-red-600 text-white"
                                    : level === "conservative"
                                    ? "bg-emerald-600 text-white"
                                    : "bg-forex-accent text-white"
                                  : "bg-slate-800 text-slate-400 hover:bg-slate-700"
                              }`}
                            >
                              {level}
                            </button>
                          ))}
                        </div>
                        <p className="text-xs text-slate-500 mt-1.5">
                          {(settings.trade_aggressiveness || "moderate") === "aggressive"
                            ? "Prefers action over inaction. Accepts lower confidence setups (0.40+). Wider stops. Higher trade frequency."
                            : (settings.trade_aggressiveness || "moderate") === "conservative"
                            ? "Only trades high-conviction setups. Requires strong multi-timeframe alignment. Prioritizes capital preservation."
                            : "Balanced approach. Trades when indicators align with reasonable confidence (0.55+). Default setting."}
                        </p>
                      </div>
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

                  <div className="border-t border-slate-700 pt-4">
                    <h3 className="text-lg font-semibold mb-4 text-slate-200">Advanced AI Options</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={settings.batched_ai_enabled === true}
                          onChange={(e) => updateField("batched_ai_enabled", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <div>
                          <span className="text-sm text-slate-300">Batched AI Prompts</span>
                          <p className="text-xs text-slate-500">Analyze all pairs in a single AI call (cheaper, cross-pair awareness)</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={settings.auto_strategy_switch_enabled === true}
                          onChange={(e) => updateField("auto_strategy_switch_enabled", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <div>
                          <span className="text-sm text-slate-300">Auto Strategy Switching</span>
                          <p className="text-xs text-slate-500">Automatically pick scalping/day/swing based on session & volatility</p>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* v2 AI Trading Team */}
                  <div className="border-t border-slate-700 pt-4">
                    <h3 className="text-lg font-semibold mb-4 text-slate-200 flex items-center gap-2">
                      <Bot className="w-5 h-5 text-forex-accent" />
                      AI Trading Team (v2)
                    </h3>
                    <p className="text-xs text-slate-500 mb-4">
                      Multi-agent engine: domain analysts → lead strategist → verifier.
                      v2 runs in parallel with v1; flip the engine version to switch.
                    </p>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-4">
                      <div>
                        <label className="text-sm text-slate-300 block mb-2">Engine Version</label>
                        <div className="flex gap-2">
                          {["v1", "v2"].map((v) => (
                            <button
                              key={v}
                              onClick={() => updateField("decision_engine_version", v)}
                              className={`px-4 py-2 rounded-lg text-sm font-semibold transition ${
                                (settings.decision_engine_version || "v1") === v
                                  ? "bg-forex-accent text-white"
                                  : "bg-slate-800 text-slate-400 hover:bg-slate-700"
                              }`}
                            >
                              {v === "v1" ? "v1 Single LLM" : "v2 Multi-Agent Team"}
                            </button>
                          ))}
                        </div>
                        <p className="text-xs text-slate-500 mt-1.5">
                          {(settings.decision_engine_version || "v1") === "v2"
                            ? "v2 uses multiple AI models: one per domain + a lead + a verifier."
                            : "v1 uses a single LLM for all decisions (legacy mode)."}
                        </p>
                      </div>

                      <div>
                        <label className="text-sm text-slate-300 block mb-2">Model Suite</label>
                        <select
                          value={settings.model_suite || "free"}
                          onChange={(e) => updateField("model_suite", e.target.value)}
                          className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm cursor-pointer"
                        >
                          <option value="free">Testing / Free</option>
                          <option value="production">Production (Free + Affordable)</option>
                          <option value="extreme">Extreme (Best Regardless of Price)</option>
                          <option value="custom">Custom (Manual Override)</option>
                        </select>
                        <p className="text-xs text-slate-500 mt-1.5">
                          Presets the per-function model assignments. Select &quot;Custom&quot; to pick each model manually.
                        </p>
                      </div>
                    </div>

                    {(settings.model_suite || "free") === "custom" && (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                        {[
                          { key: "model_technical", label: "Technical Analyst" },
                          { key: "model_fundamental", label: "Fundamental Analyst" },
                          { key: "model_sentiment", label: "Sentiment Analyst" },
                          { key: "model_macro", label: "Macro / Daily Bias" },
                          { key: "model_lead", label: "Lead Strategist" },
                          { key: "model_verifier", label: "Verifier (Risk Manager)" },
                        ].map(({ key, label }) => (
                          <div key={key}>
                            <label className="text-sm text-slate-300 block mb-1">{label}</label>
                            <select
                              value={settings[key] || ""}
                              onChange={(e) => updateField(key, e.target.value)}
                              className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                            >
                              <option value="">Default</option>
                              {Object.entries(AI_MODELS).map(([id, { label: lbl }]) => (
                                <option key={id} value={id}>{lbl}</option>
                              ))}
                            </select>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={settings.verifier_enabled !== false}
                          onChange={(e) => updateField("verifier_enabled", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <div>
                          <span className="text-sm text-slate-300">Enable Verifier</span>
                          <p className="text-xs text-slate-500">Run a risk-manager review on every trade proposal.</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={settings.verifier_can_veto !== false}
                          onChange={(e) => updateField("verifier_can_veto", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <div>
                          <span className="text-sm text-slate-300">Verifier Can Veto</span>
                          <p className="text-xs text-slate-500">If unchecked, verifier only warns (does not block).</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={settings.daily_bias_enabled !== false}
                          onChange={(e) => updateField("daily_bias_enabled", e.target.checked)}
                          className="w-4 h-4 accent-forex-accent"
                        />
                        <div>
                          <span className="text-sm text-slate-300">Daily Bias Pass</span>
                          <p className="text-xs text-slate-500">Pre-market reasoning-model digest injected into intraday prompts.</p>
                        </div>
                      </div>
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

              {/* Notifications Settings */}
              {activeTab === "notifications" && (
                <div className="bg-forex-card rounded-xl border border-slate-700 p-6 space-y-6">
                  <div className="flex items-center gap-2 mb-2">
                    <Bell className="w-5 h-5 text-forex-accent" />
                    <h2 className="text-xl font-semibold">Notifications</h2>
                  </div>
                  <p className="text-sm text-slate-400">Get alerts when trades open, close, or hit partial profits. Supports Discord, Slack, Pushover, and generic webhooks.</p>

                  <div className="grid grid-cols-1 gap-4">
                    <div>
                      <label className="text-sm text-slate-300 block mb-1">Discord Webhook URL</label>
                      <input
                        type="text"
                        value={settings.discord_webhook_url || ""}
                        onChange={(e) => updateField("discord_webhook_url", e.target.value)}
                        placeholder="https://discord.com/api/webhooks/..."
                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                      />
                    </div>
                    <div>
                      <label className="text-sm text-slate-300 block mb-1">Slack Webhook URL</label>
                      <input
                        type="text"
                        value={settings.slack_webhook_url || ""}
                        onChange={(e) => updateField("slack_webhook_url", e.target.value)}
                        placeholder="https://hooks.slack.com/services/..."
                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                      />
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm text-slate-300 block mb-1">Pushover App Token</label>
                        <input
                          type="text"
                          value={settings.pushover_app_token || ""}
                          onChange={(e) => updateField("pushover_app_token", e.target.value)}
                          className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                        />
                      </div>
                      <div>
                        <label className="text-sm text-slate-300 block mb-1">Pushover User Key</label>
                        <input
                          type="text"
                          value={settings.pushover_user_key || ""}
                          onChange={(e) => updateField("pushover_user_key", e.target.value)}
                          className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                        />
                      </div>
                    </div>
                    <div>
                      <label className="text-sm text-slate-300 block mb-1">Generic Webhook URL</label>
                      <input
                        type="text"
                        value={settings.webhook_url || ""}
                        onChange={(e) => updateField("webhook_url", e.target.value)}
                        placeholder="https://your-api.com/webhook"
                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                      />
                    </div>
                  </div>

                  <button
                    onClick={saveSettings}
                    disabled={saving}
                    className="flex items-center gap-2 bg-forex-accent hover:bg-blue-600 text-white px-4 py-2 rounded-lg font-semibold transition disabled:opacity-50"
                  >
                    <Save className="w-4 h-4" />
                    {saving ? "Saving..." : "Save Notification Settings"}
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
