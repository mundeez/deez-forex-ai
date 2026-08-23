/**
 * FX session classifier — mirrors backend app/services/sessions.py.
 * Uses UTC hour only; the caller must normalize to UTC before passing.
 */
export type SessionLabel = "asian" | "london" | "london_ny_overlap" | "ny" | "sydney";

export function classifySession(isoString?: string | null): SessionLabel | null {
  if (!isoString) return null;
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return null;
  const h = d.getUTCHours();
  if (h >= 0 && h < 7) return "asian";
  if (h >= 7 && h < 12) return "london";
  if (h >= 12 && h < 16) return "london_ny_overlap";
  if (h >= 16 && h < 21) return "ny";
  return "sydney";
}

const SESSION_LABELS: Record<SessionLabel, string> = {
  asian: "Asian",
  london: "London",
  london_ny_overlap: "L/NY",
  ny: "NY",
  sydney: "Sydney",
};

export function formatSession(label?: SessionLabel | null): string {
  if (!label) return "—";
  return SESSION_LABELS[label];
}
