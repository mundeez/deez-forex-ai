"""Centralized UTC datetime helper to prevent naive/aware timezone bugs."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def ensure_aware(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (assumes UTC if naive).

    SQLite stores DateTime(timezone=True) columns as naive strings, so
    SQLAlchemy returns naive datetimes even for aware columns. This helper
    normalizes them so subtraction/comparison never raises TypeError.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
