"use client";

import {
  AppBar,
  Toolbar,
  Typography,
  IconButton,
  Box,
  Chip,
  Tooltip,
} from "@mui/material";
import {
  Settings as SettingsIcon,
  ShowChart as ShowChartIcon,
} from "@mui/icons-material";
import Link from "next/link";

interface HeaderProps {
  connected?: boolean;
  provider?: string;
}

export default function Header({ connected = true, provider = "metaapi" }: HeaderProps) {
  return (
    <AppBar position="static" elevation={0} sx={{ borderBottom: "1px solid #1e293b" }}>
      <Toolbar sx={{ justifyContent: "space-between" }}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
          <ShowChartIcon sx={{ color: "primary.main" }} />
          <Link href="/" passHref style={{ textDecoration: "none", color: "inherit" }}>
            <Typography variant="h6" fontWeight={700} sx={{ letterSpacing: "-0.02em", cursor: "pointer" }}>
              deez-forex-ai
            </Typography>
          </Link>
        </Box>

        <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
          <Chip
            size="small"
            label={provider === "mt5_zmq" ? "MT5 Container" : "MetaAPI.cloud"}
            color="primary"
            sx={{
              bgcolor: "transparent",
              border: (theme) => `1px solid ${theme.palette.primary.main}`,
              color: (theme) => theme.palette.primary.main,
            }}
          />
          <Chip
            size="small"
            label={connected ? "24/7 Live" : "Disconnected"}
            color={connected ? "success" : "error"}
            icon={
              <Box
                component="span"
                sx={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  bgcolor: connected ? "success.main" : "error.main",
                  animation: connected ? "pulse 2s infinite" : "none",
                  mr: 0.5,
                  ml: 1,
                }}
              />
            }
            sx={{
              bgcolor: "transparent",
              border: (theme) => `1px solid ${connected ? theme.palette.success.main : theme.palette.error.main}`,
              color: (theme) => (connected ? theme.palette.success.main : theme.palette.error.main),
            }}
          />
          <Tooltip title="Settings">
            <Link href="/settings" passHref>
              <IconButton size="small" sx={{ color: "text.secondary", "&:hover": { color: "text.primary" } }}>
                <SettingsIcon />
              </IconButton>
            </Link>
          </Tooltip>
        </Box>
      </Toolbar>
    </AppBar>
  );
}
