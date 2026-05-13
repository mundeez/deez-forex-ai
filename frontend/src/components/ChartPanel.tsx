"use client";

import { useEffect, useRef, useState } from "react";
import { createChart, IChartApi, ISeriesApi, CandlestickData, Time } from "lightweight-charts";
import { API_URL } from "@/utils/api";

interface ChartPanelProps {
  symbol: string;
  timeframe: string;
  livePrice?: { bid: number; ask: number; timestamp?: string };
}

export default function ChartPanel({ symbol, timeframe, livePrice }: ChartPanelProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const ema9Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema21Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema50Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const bbUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbLowerRef = useRef<ISeriesApi<"Line"> | null>(null);
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
    const ema50 = chart.addLineSeries({ color: "#a855f7", lineWidth: 1, title: "EMA 50" });
    const bbUpper = chart.addLineSeries({ color: "#94a3b8", lineWidth: 1, lineStyle: 2, title: "BB Upper" });
    const bbLower = chart.addLineSeries({ color: "#94a3b8", lineWidth: 1, lineStyle: 2, title: "BB Lower" });

    ema9Ref.current = ema9;
    ema21Ref.current = ema21;
    ema50Ref.current = ema50;
    bbUpperRef.current = bbUpper;
    bbLowerRef.current = bbLower;

    const handleResize = () => {
      if (!chartContainerRef.current || !chartRef.current) return;
      const width = chartContainerRef.current.clientWidth;
      if (width > 0) {
        try {
          chartRef.current.applyOptions({ width });
        } catch {
          /* chart may be disposed */
        }
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      try {
        chart.remove();
      } catch {
        /* already disposed */
      }
      chartRef.current = null;
      seriesRef.current = null;
      ema9Ref.current = null;
      ema21Ref.current = null;
      ema50Ref.current = null;
      bbUpperRef.current = null;
      bbLowerRef.current = null;
    };
  }, []);

  // Update chart data when candles change
  useEffect(() => {
    if (!seriesRef.current || candles.length === 0) return;

    const chartData: CandlestickData<Time>[] = candles.map((c: any) => ({
      time: Math.floor(new Date(c.timestamp).getTime() / 1000) as Time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    try {
      seriesRef.current.setData(chartData);
    } catch {
      return;
    }

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

    function computeBB(closes: number[], period: number, stdDev: number): { upper: number[]; lower: number[] } {
      const upper: number[] = [];
      const lower: number[] = [];
      for (let i = 0; i < closes.length; i++) {
        if (i < period - 1) {
          upper.push(NaN);
          lower.push(NaN);
          continue;
        }
        const slice = closes.slice(i - period + 1, i + 1);
        const mean = slice.reduce((a, b) => a + b, 0) / period;
        const variance = slice.reduce((sum, v) => sum + Math.pow(v - mean, 2), 0) / period;
        const std = Math.sqrt(variance);
        upper.push(mean + stdDev * std);
        lower.push(mean - stdDev * std);
      }
      return { upper, lower };
    }

    const closes = candles.map((c: any) => c.close);
    const ema9Values = computeEMA(closes, 9);
    const ema21Values = computeEMA(closes, 21);
    const ema50Values = computeEMA(closes, 50);
    const bb = computeBB(closes, 20, 2);

    try {
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
      if (ema50Ref.current) {
        ema50Ref.current.setData(
          candles
            .map((c: any, i: number) => ({
              time: Math.floor(new Date(c.timestamp).getTime() / 1000) as Time,
              value: ema50Values[i],
            }))
            .filter((p: any) => !isNaN(p.value))
        );
      }
      if (bbUpperRef.current) {
        bbUpperRef.current.setData(
          candles
            .map((c: any, i: number) => ({
              time: Math.floor(new Date(c.timestamp).getTime() / 1000) as Time,
              value: bb.upper[i],
            }))
            .filter((p: any) => !isNaN(p.value))
        );
      }
      if (bbLowerRef.current) {
        bbLowerRef.current.setData(
          candles
            .map((c: any, i: number) => ({
              time: Math.floor(new Date(c.timestamp).getTime() / 1000) as Time,
              value: bb.lower[i],
            }))
            .filter((p: any) => !isNaN(p.value))
        );
      }
      if (chartRef.current) {
        chartRef.current.timeScale().fitContent();
      }
    } catch {
      /* chart disposed during update */
    }
  }, [candles]);

  // Live price tick update - update last candle
  useEffect(() => {
    if (!livePrice || !seriesRef.current || candles.length === 0) return;
    const lastCandle = candles[candles.length - 1];
    const lastTime = Math.floor(new Date(lastCandle.timestamp).getTime() / 1000) as Time;
    const price = livePrice.bid;

    try {
      seriesRef.current.update({
        time: lastTime,
        open: lastCandle.open,
        high: Math.max(lastCandle.high, price),
        low: Math.min(lastCandle.low, price),
        close: price,
      });
    } catch {
      // ignore
    }
  }, [livePrice]);

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
