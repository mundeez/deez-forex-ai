import { createSlice, PayloadAction } from "@reduxjs/toolkit";
import type { PriceTick, AnalysisResult, MarketSummary } from "@/types";

interface MarketState {
  prices: Record<string, PriceTick>;
  analysis: AnalysisResult | null;
  marketSummary: MarketSummary | null;
  candles: Record<string, any[]>;
}

const initialState: MarketState = {
  prices: {},
  analysis: null,
  marketSummary: null,
  candles: {},
};

const marketSlice = createSlice({
  name: "market",
  initialState,
  reducers: {
    setPrice(state, action: PayloadAction<PriceTick>) {
      state.prices[action.payload.symbol] = action.payload;
    },
    setPrices(state, action: PayloadAction<Record<string, PriceTick>>) {
      state.prices = { ...state.prices, ...action.payload };
    },
    setAnalysis(state, action: PayloadAction<AnalysisResult>) {
      state.analysis = action.payload;
    },
    setMarketSummary(state, action: PayloadAction<MarketSummary>) {
      state.marketSummary = action.payload;
    },
    setCandles(state, action: PayloadAction<{ symbol: string; timeframe: string; data: any[] }>) {
      const key = `${action.payload.symbol}_${action.payload.timeframe}`;
      state.candles[key] = action.payload.data;
    },
  },
});

export const { setPrice, setPrices, setAnalysis, setMarketSummary, setCandles } =
  marketSlice.actions;

export default marketSlice.reducer;
