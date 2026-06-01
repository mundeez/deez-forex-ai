"""Instrument metadata + PnL helpers shared by the mock data feed and the executor.

Centralizes per-symbol price levels, pip sizes, contract sizes and quote
currencies so that:
  * the paper/mock feed produces *realistic* per-symbol prices (not a single
    1.0850 oscillator for every pair), and
  * PnL is computed in USD with the correct pip value / contract size instead
    of a blanket ``* 100000`` (which was ~150x too large for JPY pairs and
    ~1000x too large for gold).

The quote->USD rates are static approximations — good enough for paper
simulation. With a live broker feed these helpers still produce correct pip
sizes/contract sizes; only the cross-currency conversion is approximate.
"""
from typing import Dict

# base   : anchor price for the mock random walk
# pip    : pip size (price increment of "1 pip")
# spread : typical bid/ask spread in price units
# step   : per-tick random-walk std-dev in price units
# contract: units per 1.0 lot (FX standard lot = 100k; gold = 100 oz)
# quote  : quote currency (used for USD conversion of PnL)
INSTRUMENTS: Dict[str, dict] = {
    "EURUSD": {"base": 1.0850, "pip": 0.0001, "spread": 0.00008, "step": 0.00035, "contract": 100000, "quote": "USD"},
    "GBPUSD": {"base": 1.2700, "pip": 0.0001, "spread": 0.00012, "step": 0.00045, "contract": 100000, "quote": "USD"},
    "AUDUSD": {"base": 0.6600, "pip": 0.0001, "spread": 0.00010, "step": 0.00030, "contract": 100000, "quote": "USD"},
    "NZDUSD": {"base": 0.6100, "pip": 0.0001, "spread": 0.00014, "step": 0.00030, "contract": 100000, "quote": "USD"},
    "USDJPY": {"base": 157.00, "pip": 0.01, "spread": 0.010, "step": 0.045, "contract": 100000, "quote": "JPY"},
    "USDCHF": {"base": 0.9000, "pip": 0.0001, "spread": 0.00015, "step": 0.00030, "contract": 100000, "quote": "CHF"},
    "USDCAD": {"base": 1.3600, "pip": 0.0001, "spread": 0.00015, "step": 0.00035, "contract": 100000, "quote": "CAD"},
    "EURGBP": {"base": 0.8550, "pip": 0.0001, "spread": 0.00012, "step": 0.00025, "contract": 100000, "quote": "GBP"},
    "GBPJPY": {"base": 199.00, "pip": 0.01, "spread": 0.025, "step": 0.065, "contract": 100000, "quote": "JPY"},
    "XAUUSD": {"base": 2350.0, "pip": 0.10, "spread": 0.30, "step": 1.40, "contract": 100, "quote": "USD"},
    # Crypto
    "BTCUSD": {"base": 65000.0, "pip": 1.0, "spread": 15.0, "step": 60.0, "contract": 1, "quote": "USD"},
    "ETHUSD": {"base": 3500.0, "pip": 0.10, "spread": 0.80, "step": 3.0, "contract": 1, "quote": "USD"},
    # Indices (CFD)
    "US30": {"base": 42000.0, "pip": 1.0, "spread": 3.0, "step": 12.0, "contract": 1, "quote": "USD"},
    "NAS100": {"base": 19500.0, "pip": 1.0, "spread": 2.0, "step": 6.0, "contract": 1, "quote": "USD"},
    "SPX500": {"base": 5800.0, "pip": 0.10, "spread": 0.40, "step": 1.5, "contract": 1, "quote": "USD"},
}

DEFAULT = {"base": 1.1000, "pip": 0.0001, "spread": 0.00010, "step": 0.00035, "contract": 100000, "quote": "USD"}

# Rough static quote-currency -> USD conversion (paper/mock approximation).
QUOTE_USD = {
    "USD": 1.0,
    "JPY": 1.0 / 157.0,
    "CHF": 1.0 / 0.90,
    "CAD": 1.0 / 1.36,
    "GBP": 1.27,
    "AUD": 0.66,
    "NZD": 0.61,
    "EUR": 1.085,
}


def meta(symbol: str) -> dict:
    return INSTRUMENTS.get(symbol, DEFAULT)


def pip_size(symbol: str) -> float:
    return meta(symbol)["pip"]


def contract_size(symbol: str) -> int:
    return meta(symbol)["contract"]


def quote_currency(symbol: str) -> str:
    return meta(symbol)["quote"]


def price_decimals(symbol: str) -> int:
    pip = pip_size(symbol)
    if pip >= 0.1:
        return 2
    if pip >= 0.01:
        return 3
    return 5


def pips(symbol: str, price_diff: float) -> float:
    """Convert a raw price difference into pips for the given symbol."""
    p = pip_size(symbol)
    return (price_diff / p) if p else 0.0


def pnl_usd(symbol: str, is_buy: bool, entry: float, exit_price: float, size: float) -> float:
    """Profit/loss in USD for a position.

    pnl = price_diff * contract_size * lots, converted from quote ccy to USD.
    """
    if not entry or not exit_price or not size:
        return 0.0
    diff = (exit_price - entry) if is_buy else (entry - exit_price)
    pnl_quote = diff * contract_size(symbol) * size
    return pnl_quote * QUOTE_USD.get(quote_currency(symbol), 1.0)
