import { useEffect, useRef, useState, useCallback } from "react";

export function useWebSocket(url: string, symbols: string[]) {
  const ws = useRef<WebSocket | null>(null);
  const [prices, setPrices] = useState<Record<string, { bid: number; ask: number; timestamp?: string }>>({});
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
      socket.send(JSON.stringify({ action: "subscribe_prices", symbols }));
    };

    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "price_tick" && msg.symbol) {
          setPrices((prev) => ({
            ...prev,
            [msg.symbol]: { bid: msg.bid, ask: msg.ask, timestamp: msg.timestamp },
          }));
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
  }, [url, symbols.join(",")]);

  return { prices, connected, send };
}
