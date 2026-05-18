import { createSlice, PayloadAction } from "@reduxjs/toolkit";
import type { AppSettings } from "@/types";

interface SettingsState {
  data: AppSettings | null;
  isLoading: boolean;
  error: string | null;
}

const initialState: SettingsState = {
  data: null,
  isLoading: false,
  error: null,
};

const settingsSlice = createSlice({
  name: "settings",
  initialState,
  reducers: {
    setSettings(state, action: PayloadAction<AppSettings>) {
      state.data = action.payload;
      state.error = null;
    },
    updateSetting(state, action: PayloadAction<Partial<AppSettings>>) {
      if (state.data) {
        state.data = { ...state.data, ...action.payload };
      }
    },
    setSettingsLoading(state, action: PayloadAction<boolean>) {
      state.isLoading = action.payload;
    },
    setSettingsError(state, action: PayloadAction<string | null>) {
      state.error = action.payload;
    },
  },
});

export const { setSettings, updateSetting, setSettingsLoading, setSettingsError } =
  settingsSlice.actions;

export default settingsSlice.reducer;
