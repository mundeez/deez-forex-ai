import { useEffect, useRef, useState, useCallback } from "react";

export interface PriceData {
  bid: number;
  ask: number;
  timestamp?: string;
}

export interface TradeEvent {
  event: string;
  data: {
    id: number;
    symbol: string;
    direction: string;
    entry_price?: number;
    exit_price?: number;
    pnl?: number;
    pnl_pct?: number;
    mode: string;
    ai_decision_id?: number;
  };
}

export interface AIDecisionEvent {
  id: number;
  symbol: string;
  decision: string;
  confidence: number;
  timeframe?: string;
  entry_price?: number;
  stop_loss?: number;
  take_profit?: number;
  position_size_pct?: number;
  risk_reward?: number;
  rationale?: string;
  manual_override?: boolean;
}

export interface SettingsChangeEvent {
  type: string;
  settings?: Record<string, any>;
  manual_override?: boolean;
  equity?: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  open_trades?: number;
}

export function useWebSocket(url: string, symbols: string[], provider?: string) {
  const ws = useRef<WebSocket | null>(null);
  const [prices, setPrices] = useState<Record<string, PriceData>>({});
  const [tradeEvents, setTradeEvents] = useState<TradeEvent[]>([]);
  const [aiDecisions, setAiDecisions] = useState<AIDecisionEvent[]>([]);
  const [settingsChanges, setSettingsChanges] = useState<SettingsChangeEvent[]>([]);
  const [connected, setConnected] = useState(false);

  const send = useCallback((msg: object) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(msg));
    }
  }, []);

  useEffect(() => {
    if (!url) return;
    const socket = new WebSocket(url);
    ws.current = socket;

    socket.onopen = () => {
      setConnected(true);
      const subMsg: any = { action: "subscribe_prices", symbols };
      if (provider) subMsg.provider = provider;
      socket.send(JSON.stringify(subMsg));
      socket.send(JSON.stringify({ action: "subscribe_topics", topics: ["prices", "trades", "ai_decisions", "settings"] }));
    };

    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "price_tick" && msg.symbol) {
          setPrices((prev) => ({
            ...prev,
            [msg.symbol]: { bid: msg.bid, ask: msg.ask, timestamp: msg.timestamp },
          }));
        } else if (msg.type === "trade_event") {
          setTradeEvents((prev) => [msg, ...prev].slice(0, 50));
        } else if (msg.type === "ai_decision") {
          setAiDecisions((prev) => [msg.data, ...prev].slice(0, 20));
        } else if (msg.type === "settings_change") {
          setSettingsChanges((prev) => [msg.data, ...prev].slice(0, 20));
        }
      } catch {
        // ignore malformed
      }
    };

    socket.onclose = () => setConnected(false);
    socket.onerror = () => setConnected(false);

    return () => {
      socket.close();
    };
  }, [url, symbols.join(","), provider]);

  return { prices, tradeEvents, aiDecisions, settingsChanges, connected, send };
}
