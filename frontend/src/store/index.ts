/**
 * Redux store configuration for deez-forex-ai frontend.
 * Uses Redux Toolkit for minimal boilerplate.
 */

import { configureStore } from "@reduxjs/toolkit";
import tradingReducer from "./slices/tradingSlice";
import marketReducer from "./slices/marketSlice";
import settingsReducer from "./slices/settingsSlice";
import uiReducer from "./slices/uiSlice";

export const store = configureStore({
  reducer: {
    trading: tradingReducer,
    market: marketReducer,
    settings: settingsReducer,
    ui: uiReducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: {
        // Ignore non-serializable values in specific actions if needed
        ignoredActions: [],
      },
    }),
  devTools: process.env.NODE_ENV !== "production",
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
