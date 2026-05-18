import { useEffect, useRef, useState, useCallback } from "react";
import type { PriceTick, WebSocketMessage } from "@/types";

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

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 15000, 30000]; // max 30s
const MAX_RECONNECT_DELAY = 30000;

export function useWebSocket(url: string, symbols: string[], provider?: string) {
  const ws = useRef<WebSocket | null>(null);
  const reconnectAttempt = useRef(0);
  const reconnectTimer = useRef<NodeJS.Timeout | null>(null);
  const [prices, setPrices] = useState<Record<string, PriceData>>({});
  const [tradeEvents, setTradeEvents] = useState<TradeEvent[]>([]);
  const [aiDecisions, setAiDecisions] = useState<AIDecisionEvent[]>([]);
  const [settingsChanges, setSettingsChanges] = useState<SettingsChangeEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);

  const connect = useCallback(() => {
    if (!url || ws.current?.readyState === WebSocket.OPEN) return;

    try {
      const socket = new WebSocket(url);
      ws.current = socket;

      socket.onopen = () => {
        setConnected(true);
        reconnectAttempt.current = 0;
        const subMsg: any = { action: "subscribe_prices", symbols };
        if (provider) subMsg.provider = provider;
        socket.send(JSON.stringify(subMsg));
        socket.send(
          JSON.stringify({
            action: "subscribe_topics",
            topics: ["prices", "trades", "ai_decisions", "settings"],
          })
        );
      };

      socket.onmessage = (event) => {
        const start = performance.now();
        try {
          const msg: WebSocketMessage = JSON.parse(event.data);
          switch (msg.type) {
            case "price_tick":
              if (msg.symbol) {
                setPrices((prev) => ({
                  ...prev,
                  [msg.symbol]: { bid: msg.bid, ask: msg.ask, timestamp: msg.timestamp },
                }));
              }
              break;
            case "trade_event":
              setTradeEvents((prev) => [msg as any, ...prev].slice(0, 50));
              break;
            case "ai_decision":
              setAiDecisions((prev) => [(msg as any).data, ...prev].slice(0, 20));
              break;
            case "settings_change":
              setSettingsChanges((prev) => [(msg as any).data, ...prev].slice(0, 20));
              break;
            case "pong":
              // Keepalive response
              break;
          }
        } catch {
          // Silently ignore malformed messages
        }
        setLatencyMs(Math.round(performance.now() - start));
      };

      socket.onclose = () => {
        setConnected(false);
        ws.current = null;
        // Schedule reconnection with exponential backoff
        const delay =
          reconnectAttempt.current < RECONNECT_DELAYS.length
            ? RECONNECT_DELAYS[reconnectAttempt.current]
            : MAX_RECONNECT_DELAY;
        reconnectAttempt.current += 1;
        reconnectTimer.current = setTimeout(connect, delay);
      };

      socket.onerror = () => {
        setConnected(false);
        // onclose will handle reconnection
      };
    } catch {
      // Connection failed immediately, schedule retry
      const delay =
        reconnectAttempt.current < RECONNECT_DELAYS.length
          ? RECONNECT_DELAYS[reconnectAttempt.current]
          : MAX_RECONNECT_DELAY;
      reconnectAttempt.current += 1;
      reconnectTimer.current = setTimeout(connect, delay);
    }
  }, [url, symbols.join(","), provider]);

  const send = useCallback((msg: object) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(msg));
    }
  }, []);

  // Initial connection + keepalive ping
  useEffect(() => {
    connect();
    const pingInterval = setInterval(() => {
      send({ action: "ping" });
    }, 30000);
    return () => {
      clearInterval(pingInterval);
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (ws.current) {
        ws.current.onclose = null;
        ws.current.close();
      }
    };
  }, [connect, send]);

  return { prices, tradeEvents, aiDecisions, settingsChanges, connected, latencyMs, send };
}
