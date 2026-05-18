import { createSlice, PayloadAction } from "@reduxjs/toolkit";
import type { Trade, AIDecision } from "@/types";

interface TradingState {
  positions: Trade[];
  tradeHistory: Trade[];
  aiDecisions: AIDecision[];
  portfolio: {
    equity: number;
    daily_pnl: number;
    unrealized_pnl: number;
    realized_pnl: number;
    win_rate: number | null;
    profit_factor: number | null;
    sharpe_ratio: number;
    max_drawdown_pct: number;
    total_trades: number;
    open_trades: number;
  } | null;
}

const initialState: TradingState = {
  positions: [],
  tradeHistory: [],
  aiDecisions: [],
  portfolio: null,
};

const tradingSlice = createSlice({
  name: "trading",
  initialState,
  reducers: {
    setPositions(state, action: PayloadAction<Trade[]>) {
      state.positions = action.payload;
    },
    updatePosition(state, action: PayloadAction<Trade>) {
      const idx = state.positions.findIndex((p) => p.id === action.payload.id);
      if (idx >= 0) {
        state.positions[idx] = action.payload;
      } else {
        state.positions.push(action.payload);
      }
    },
    removePosition(state, action: PayloadAction<number>) {
      state.positions = state.positions.filter((p) => p.id !== action.payload);
    },
    setTradeHistory(state, action: PayloadAction<Trade[]>) {
      state.tradeHistory = action.payload;
    },
    addTradeToHistory(state, action: PayloadAction<Trade>) {
      state.tradeHistory.unshift(action.payload);
    },
    setAIDecisions(state, action: PayloadAction<AIDecision[]>) {
      state.aiDecisions = action.payload;
    },
    addAIDecision(state, action: PayloadAction<AIDecision>) {
      state.aiDecisions.unshift(action.payload);
      // Keep only the last 20 decisions
      if (state.aiDecisions.length > 20) {
        state.aiDecisions.pop();
      }
    },
    setPortfolio(state, action: PayloadAction<TradingState["portfolio"]>) {
      state.portfolio = action.payload;
    },
  },
});

export const {
  setPositions,
  updatePosition,
  removePosition,
  setTradeHistory,
  addTradeToHistory,
  setAIDecisions,
  addAIDecision,
  setPortfolio,
} = tradingSlice.actions;

export default tradingSlice.reducer;
