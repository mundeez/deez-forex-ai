"""Strategy variant engine — Phase 7.1.

Rules originate direction; the LLM layer may only veto. Every registered
variant exposes generate() -> list[Candidate] over a dict of candle lists
keyed by timeframe ("5m","15m","1h","4h","1d"). Candles are dicts with
timestamp (unix), open, high, low, close.
"""
from app.strategies.engine import (
    Candidate,
    VARIANTS,
    VARIANT_PAIRS,
    FX_PAIRS,
    generate_all,
    regime_of,
    instrument,
    pip_size,
)

__all__ = [
    "Candidate", "VARIANTS", "VARIANT_PAIRS", "FX_PAIRS",
    "generate_all", "regime_of", "instrument", "pip_size",
]
