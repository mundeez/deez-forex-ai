"""FX session classifier.

Centralizes session-of-day labelling so backend and frontend agree on the
same buckets. UTC-only — caller is responsible for timezone normalization.

Bucket boundaries (UTC hours):
    asian             00:00 – 06:59
    london            07:00 – 11:59
    london_ny_overlap 12:00 – 15:59
    ny                16:00 – 20:59
    sydney            21:00 – 23:59
"""
from datetime import datetime
from typing import Optional


SESSION_LABELS = ("asian", "london", "london_ny_overlap", "ny", "sydney")


def classify_session(dt_utc: Optional[datetime]) -> Optional[str]:
    """Return the FX session label for the given UTC timestamp.

    Returns ``None`` when ``dt_utc`` is ``None`` so callers can chain safely.
    Inputs are interpreted as UTC even if naive (matches the rest of the
    codebase which uses ``utc_now()`` from app.utils.time).
    """
    if dt_utc is None:
        return None
    h = dt_utc.hour
    if 0 <= h < 7:
        return "asian"
    if 7 <= h < 12:
        return "london"
    if 12 <= h < 16:
        return "london_ny_overlap"
    if 16 <= h < 21:
        return "ny"
    return "sydney"
