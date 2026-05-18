"use client";

import { Provider } from "react-redux";
import { ThemeProvider } from "@mui/material/styles";
import { CssBaseline } from "@mui/material";
import { Toaster } from "sonner";
import { store } from "@/store";
import { theme } from "@/theme";

export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <Provider store={store}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <Toaster
          position="top-right"
          toastOptions={{
            style: {
              background: "#111827",
              color: "#f1f5f9",
              border: "1px solid #1e293b",
            },
          }}
        />
        {children}
      </ThemeProvider>
    </Provider>
  );
}