export function formatNumber(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

export function formatPnl(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const sign = n >= 0 ? "+" : "";
  return `${sign}$${n.toFixed(2)}`;
}

export function formatPercent(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

export function formatDuration(minutes?: number | null): string {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes)) return "—";
  const h = Math.floor(minutes / 60);
  const m = Math.floor(minutes % 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export function computeRMultiple(
  pnlPct: number | null | undefined,
  entryPrice: number | null | undefined,
  stopLoss: number | null | undefined,
  riskPct: number | null | undefined
): number | null {
  if (pnlPct === null || pnlPct === undefined || Number.isNaN(pnlPct)) return null;

  // Prefer the stored risk percentage if available.
  if (riskPct !== null && riskPct !== undefined && riskPct > 0) {
    return pnlPct / riskPct;
  }

  // Fallback: derive rough R from the price distance to SL.
  if (entryPrice && stopLoss && entryPrice > 0) {
    const slDistance = Math.abs(entryPrice - stopLoss) / entryPrice * 100;
    if (slDistance > 0) {
      return pnlPct / slDistance;
    }
  }

  return null;
}
