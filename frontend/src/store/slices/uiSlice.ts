import { createSlice, PayloadAction } from "@reduxjs/toolkit";

interface UIState {
  connectionStatus: "connected" | "disconnected" | "connecting";
  selectedPair: string;
  selectedTimeframe: string;
  activeTab: string;
  isManualOverride: boolean;
  toastMessage: string | null;
}

const initialState: UIState = {
  connectionStatus: "connecting",
  selectedPair: "EURUSD",
  selectedTimeframe: "1h",
  activeTab: "dashboard",
  isManualOverride: false,
  toastMessage: null,
};

const uiSlice = createSlice({
  name: "ui",
  initialState,
  reducers: {
    setConnectionStatus(state, action: PayloadAction<UIState["connectionStatus"]>) {
      state.connectionStatus = action.payload;
    },
    setSelectedPair(state, action: PayloadAction<string>) {
      state.selectedPair = action.payload;
    },
    setSelectedTimeframe(state, action: PayloadAction<string>) {
      state.selectedTimeframe = action.payload;
    },
    setActiveTab(state, action: PayloadAction<string>) {
      state.activeTab = action.payload;
    },
    setManualOverride(state, action: PayloadAction<boolean>) {
      state.isManualOverride = action.payload;
    },
    showToast(state, action: PayloadAction<string>) {
      state.toastMessage = action.payload;
    },
    clearToast(state) {
      state.toastMessage = null;
    },
  },
});

export const {
  setConnectionStatus,
  setSelectedPair,
  setSelectedTimeframe,
  setActiveTab,
  setManualOverride,
  showToast,
  clearToast,
} = uiSlice.actions;

export default uiSlice.reducer;
