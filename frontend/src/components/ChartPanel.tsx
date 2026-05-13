"use client";

import { useEffect, useRef, useState } from "react";
import { createChart, IChartApi, ISeriesApi, CandlestickData, Time } from "lightweight-charts";
import { API_URL } from "@/utils/api";

interface ChartPanelProps {
  symbol: string;
  timeframe: string;
}

export default function ChartPanel({ symbol, timeframe }: ChartPanelProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const ema9Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema21Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const [candles, setCandles] = useState<any[]>([]);

  useEffect(() => {
    fetchCandles();
    const interval = setInterval(fetchCandles, 30000);
    return () => clearInterval(interval);
  }, [symbol, timeframe]);

  async function fetchCandles() {
    try {
      const res = await fetch(
        `${API_URL}/api/v1/market/historical?symbol=${symbol}&timeframe=${timeframe}&limit=300`
      );
      if (!res.ok) return;
      const data = await res.json();
      setCandles(data.candles || []);
    } catch (e) {
      console.error("candles fetch error", e);
    }
  }

  useEffect(() => {
    if (!chartContainerRef.current) return;
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: "#0f172a" },
        textColor: "#cbd5e1",
      },
      grid: {
        vertLines: { color: "#1e293b" },
        horzLines: { color: "#1e293b" },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: "#334155" },
      timeScale: { borderColor: "#334155" },
      width: chartContainerRef.current.clientWidth,
      height: 400,
    });
    chartRef.current = chart;

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#10b981",
      downColor: "#ef4444",
      borderUpColor: "#10b981",
      borderDownColor: "#ef4444",
      wickUpColor: "#10b981",
      wickDownColor: "#ef4444",
    });
    seriesRef.current = candleSeries;

    const ema9 = chart.addLineSeries({ color: "#f59e0b", lineWidth: 1, title: "EMA 9" });
    const ema21 = chart.addLineSeries({ color: "#3b82f6", lineWidth: 1, title: "EMA 21" });
    ema9Ref.current = ema9;
    ema21Ref.current = ema21;

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || candles.length === 0) return;

    const chartData: CandlestickData<Time>[] = candles.map((c: any) => ({
      time: Math.floor(new Date(c.timestamp).getTime() / 1000) as Time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    seriesRef.current.setData(chartData);

    function computeEMA(closes: number[], period: number): number[] {
      const k = 2 / (period + 1);
      const ema: number[] = [];
      let prev = closes.slice(0, period).reduce((a, b) => a + b, 0) / period;
      for (let i = 0; i < closes.length; i++) {
        if (i < period - 1) {
          ema.push(NaN);
        } else if (i === period - 1) {
          ema.push(prev);
        } else {
          prev = closes[i] * k + prev * (1 - k);
          ema.push(prev);
        }
      }
      return ema;
    }

    const closes = candles.map((c: any) => c.close);
    const ema9Values = computeEMA(closes, 9);
    const ema21Values = computeEMA(closes, 21);

    if (ema9Ref.current) {
      ema9Ref.current.setData(
        candles
          .map((c: any, i: number) => ({
            time: Math.floor(new Date(c.timestamp).getTime() / 1000) as Time,
            value: ema9Values[i],
          }))
          .filter((p: any) => !isNaN(p.value))
      );
    }
    if (ema21Ref.current) {
      ema21Ref.current.setData(
        candles
          .map((c: any, i: number) => ({
            time: Math.floor(new Date(c.timestamp).getTime() / 1000) as Time,
            value: ema21Values[i],
          }))
          .filter((p: any) => !isNaN(p.value))
      );
    }

    if (chartRef.current) {
      chartRef.current.timeScale().fitContent();
    }
  }, [candles]);

  return (
    <div className="bg-forex-card rounded-xl border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-semibold text-slate-200">{symbol} Chart</h2>
        <span className="text-xs text-slate-400">{timeframe}</span>
      </div>
      <div ref={chartContainerRef} className="w-full" />
    </div>
  );
}
