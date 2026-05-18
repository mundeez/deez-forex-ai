"use client";

import { Card, CardContent, Typography, Box, Chip, Skeleton } from "@mui/material";
import { TrendingUp, TrendingDown } from "@mui/icons-material";
import type { MarketSummary } from "@/types";

interface MarketCardProps {
  data?: MarketSummary | null;
  error?: string | null;
  symbol?: string;
}

export default function MarketCard({ data, error, symbol }: MarketCardProps) {
  if (error) {
    return (
      <Card sx={{ borderColor: "error.main" }}>
        <CardContent>
          <Typography color="error" fontWeight={500}>
            Failed to load market data
          </Typography>
          <Typography color="error.light" variant="body2" sx={{ mt: 0.5 }}>
            {error}
          </Typography>
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card>
        <CardContent>
          <Skeleton variant="text" width="40%" height={32} />
          <Box sx={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 2, mt: 2 }}>
            <Skeleton variant="text" height={40} />
            <Skeleton variant="text" height={40} />
            <Skeleton variant="text" height={40} />
          </Box>
        </CardContent>
      </Card>
    );
  }

  const spread = data.ask && data.bid ? (data.ask - data.bid).toFixed(5) : "-";
  const displaySymbol = symbol || data.symbol || "EUR/USD";
  const isPositive = (data.day_change_pct ?? 0) >= 0;

  return (
    <Card>
      <CardContent>
        <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 2 }}>
          <Typography variant="h6" fontWeight={600}>
            {displaySymbol}
          </Typography>
          <Chip size="small" label="Spot" variant="outlined" sx={{ fontSize: "0.75rem" }} />
        </Box>
        <Box sx={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 2 }}>
          <Box>
            <Typography variant="caption" color="text.secondary">
              Bid
            </Typography>
            <Typography variant="h4" fontWeight={700} color="success.main">
              {data.bid?.toFixed(5) ?? "-"}
            </Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">
              Ask
            </Typography>
            <Typography variant="h4" fontWeight={700} color="error.main">
              {data.ask?.toFixed(5) ?? "-"}
            </Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">
              Spread
            </Typography>
            <Typography variant="h4" fontWeight={700}>
              {spread}
            </Typography>
          </Box>
        </Box>
        {data.day_change_pct !== null && (
          <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, mt: 2 }}>
            {isPositive ? (
              <TrendingUp fontSize="small" color="success" />
            ) : (
              <TrendingDown fontSize="small" color="error" />
            )}
            <Typography
              variant="body2"
              color={isPositive ? "success.main" : "error.main"}
              fontWeight={500}
            >
              {isPositive ? "+" : ""}
              {data.day_change_pct?.toFixed(4) ?? 0}% today
            </Typography>
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
