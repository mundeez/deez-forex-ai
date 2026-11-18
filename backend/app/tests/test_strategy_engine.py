"""Regression tests for the Phase 7 strategy tournament engine.

Covers the timestamp-unit fixes: the MT5 feed returns millisecond epoch
candles while `now` and event times are seconds. Session-breakout,
news-drift, and regime/session helpers must normalize units or the
variants are dead by construction.
"""
import time
from datetime import datetime, timezone

from app.strategies.engine import (
    _event_ts,
    _mean_reversion,
    _news_drift,
    _session_breakout,
    _session_of,
    _ts_sec,
    Candidate,
    atr,
    adx,
    generate_all,
    rsi,
    stop_pips_ok,
    bollinger,
    _closes,
)


def _candle(ts_sec, o, h, l, c):
    return {"timestamp": int(ts_sec * 1000), "open": o, "high": h,
            "low": l, "close": c}


def _day0(now):
    return datetime.fromtimestamp(now, tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp()


def _sb_candles(day0, now_sb):
    """15m candles: tight 00:00-07:00 UTC range, breakout during 07-10 window."""
    c = []
    px = 1.1000
    for i in range(28):  # 00:00 -> 06:45
        c.append(_candle(day0 + i * 900, px, px + 0.0001, px - 0.0001, px))
    for i in range(4):    # 07:00 -> 07:45 breakout
        cl = px + (0.0005 if i >= 1 else 0.0)
        c.append(_candle(day0 + 7 * 3600 + i * 900, px, cl + 0.0001,
                         px - 0.0001, cl))
        px = cl
    return c


def _d1_candles(day0, n=60, span=0.0002):
    return [_candle(day0 - i * 86400, 1.1, 1.1 + span / 2,
                    1.1 - span / 2, 1.1) for i in range(n)]


class TestTimestampNormalization:
    def test_ts_sec_ms_and_sec(self):
        assert _ts_sec(1794942900000) == 1794942900.0
        assert _ts_sec(1794942900) == 1794942900.0
        assert _ts_sec(1794942900.5) == 1794942900.5

    def test_session_of_ms_timestamp(self):
        # 2026-11-17 08:00 UTC in ms -> london session
        ts_ms = int(datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc)
                    .timestamp() * 1000)
        assert _session_of(ts_ms) == "london"
        assert _session_of(ts_ms / 1000) == "london"

    def test_event_ts_db_and_ff_shapes(self):
        db_ev = {"title": "CPI", "country": "USD", "impact": "high",
                 "date": "2026-11-17T12:30:00+00:00"}
        assert _event_ts(db_ev) == datetime(
            2026, 11, 17, 12, 30, tzinfo=timezone.utc).timestamp()
        ff_ev = {"title": "CPI", "country": "USD", "impact": "3",
                 "date": "2026-11-17T08:30:00-05:00", "time": "8:30am"}
        assert _event_ts(ff_ev) == datetime(
            2026, 11, 17, 13, 30, tzinfo=timezone.utc).timestamp()
        assert _event_ts({"title": "x"}) is None
        assert _event_ts({"date": "not-a-date"}) is None


class TestSessionBreakout:
    def test_fires_inside_london_window_ms_timestamps(self):
        now = time.time()
        day0 = _day0(now)
        now_sb = day0 + 8 * 3600  # 08:00 UTC — inside 07-10 entry window
        c = _sb_candles(day0, now_sb)
        d1 = _d1_candles(day0)
        out = _session_breakout("SB-M15-LDN", "15m", 0, 7, 10, 12,
                                "EURUSD", c, d1, now_sb)
        assert len(out) == 1
        assert out[0].variant_id == "SB-M15-LDN"
        assert out[0].direction == "BUY"
        assert out[0].timeframe == "15m"

    def test_empty_outside_entry_window(self):
        now = time.time()
        day0 = _day0(now)
        now_sb = day0 + 8 * 3600
        c = _sb_candles(day0, now_sb)
        d1 = _d1_candles(day0)
        out = _session_breakout("SB-M15-LDN", "15m", 0, 7, 10, 12,
                                "EURUSD", c, d1, day0 + 12 * 3600)
        assert out == []

    def test_empty_before_window_opens(self):
        now = time.time()
        day0 = _day0(now)
        now_sb = day0 + 8 * 3600
        c = _sb_candles(day0, now_sb)
        d1 = _d1_candles(day0)
        out = _session_breakout("SB-M15-LDN", "15m", 0, 7, 10, 12,
                                "EURUSD", c, d1, day0 + 6 * 3600)
        assert out == []


class TestNewsDrift:
    def _candles_around_event(self, ets, now):
        """62 15m candles (ms ts) flat at 1.1000, +0.002 spike in first
        post-event candle."""
        c = []
        base = 1.1000
        t0 = int((now - 60 * 900) * 1000)
        for i in range(62):
            ts = t0 + i * 900000
            sec = ts / 1000
            cl = base + (0.002 if sec >= ets else 0.0)
            c.append({"timestamp": ts, "open": cl - 0.0001,
                      "high": cl + 0.0002, "low": cl - 0.0002, "close": cl})
        return c

    def test_fires_with_db_shaped_event(self):
        now = time.time()
        ets = now - 30 * 60  # event 30 min ago — inside 15-90 min window
        c = self._candles_around_event(ets, now)
        ev = {"title": "CPI m/m", "country": "USD", "impact": "high",
              "date": datetime.fromtimestamp(ets, tz=timezone.utc).isoformat()}
        out = _news_drift("ND-M15-DRIFT", "EURUSD", c, [ev], now)
        assert len(out) == 1
        assert out[0].direction == "BUY"
        assert out[0].variant_id == "ND-M15-DRIFT"

    def test_ignores_event_outside_delay_window(self):
        now = time.time()
        ets = now - 3 * 3600  # 3h ago — too old
        c = self._candles_around_event(ets - 3600, now)
        ev = {"title": "CPI m/m", "country": "USD", "impact": "high",
              "date": datetime.fromtimestamp(ets, tz=timezone.utc).isoformat()}
        assert _news_drift("ND-M15-DRIFT", "EURUSD", c, [ev], now) == []

    def test_ignores_unparseable_event_time(self):
        now = time.time()
        c = self._candles_around_event(now - 3600, now)
        ev = {"title": "x", "country": "USD", "impact": "high",
              "time": "8:30am"}  # FF display string, no ISO date
        assert _news_drift("ND-M15-DRIFT", "EURUSD", c, [ev], now) == []


class TestMeanReversion:
    def _ranging_then_dump_candles(self, n=60, drop=0.006):
        """Flat 1h candles then a single gap-down candle -> close beyond the
        lower BB(20,2.5) with RSI~0 and ADX~0 (no sustained trend)."""
        c = []
        base = 1.1000
        for i in range(n - 1):
            c.append(_candle(1700000000 + i * 3600, base, base + 0.0001,
                             base - 0.0001, base))
        cl = base - drop
        c.append(_candle(1700000000 + (n - 1) * 3600, base, base + 0.0001,
                         cl - 0.0002, cl))
        return c

    def test_gate_values_are_computable(self):
        c = self._ranging_then_dump_candles()
        assert atr(c) is not None
        assert adx(c) is not None
        assert rsi(_closes(c)) is not None
        up, mid, lo = bollinger(_closes(c), 20, 2.5)
        assert lo is not None and c[-1]["close"] < lo

    def test_fires_on_band_break_with_low_adx(self):
        c = self._ranging_then_dump_candles()
        if adx(c) >= 20:
            pytest.skip("synthetic dump produced ADX>=20")
        out = _mean_reversion("MR-H1-BBFADE", "EURUSD", c)
        assert len(out) == 1
        assert out[0].direction == "BUY"
        assert out[0].variant_id == "MR-H1-BBFADE"

    def test_empty_when_adx_too_high(self):
        # Sustained uptrend -> ADX >= 20 must block the fade even though
        # price stretches beyond the upper band with RSI > 75.
        c = []
        base = 1.1000
        for i in range(60):
            cl = base + i * 0.0004
            c.append(_candle(1700000000 + i * 3600, cl - 0.0004,
                             cl + 0.0002, cl - 0.0006, cl))
        assert adx(c) >= 20
        assert _mean_reversion("MR-H1-BBFADE", "EURUSD", c) == []


class TestGenerateAll:
    def test_runs_with_mt5_style_ms_candles(self):
        now = time.time()
        day0 = _day0(now)
        candles_by_tf = {
            "5m": [_candle(day0 + i * 300, 1.1, 1.1002, 1.0998, 1.1)
                   for i in range(60)],
            "15m": _sb_candles(day0, day0 + 8 * 3600),
            "1h": [_candle(day0 + i * 3600, 1.1, 1.1005, 1.0995, 1.1)
                   for i in range(60)],
            "4h": [_candle(day0 + i * 14400, 1.1, 1.1005, 1.0995, 1.1)
                   for i in range(60)],
            "1d": _d1_candles(day0, n=60),
        }
        # now inside the SB-M15-LDN window, no events
        out = generate_all("EURUSD", candles_by_tf, [], day0 + 8 * 3600)
        assert isinstance(out, list)
        # The 15m breakout candles must surface an SB candidate now that
        # timestamps are normalized (previously impossible with ms feed).
        assert any(c.variant_id == "SB-M15-LDN" for c in out)


class TestStopPipsOk:
    """Micro-stop gate: fixed-$5 sizing divides by stop distance, so a stop
    inside ~5 pips (or <0.5x ATR) produces an oversized position that news
    noise runs over — e.g. ND-M15-DRIFT trade 4367 lost -$18 on a 3.7-pip
    stop."""

    def _cand(self, entry=1.1000, sl=1.09963, atr=0.0004):
        return Candidate("ND-M15-DRIFT", "EURUSD", "SELL", entry, sl,
                         entry - 0.00055, atr, "15m")

    def test_rejects_micro_stop(self):
        # 3.7-pip stop on EURUSD with ~4-pip ATR — the 4367 case
        assert not stop_pips_ok(self._cand(), "EURUSD")

    def test_accepts_normal_stop(self):
        # 12-pip stop, 4-pip ATR
        assert stop_pips_ok(self._cand(sl=1.0988), "EURUSD")

    def test_atr_floor_scales_with_volatility(self):
        # 6-pip stop passes the 5-pip floor in quiet tape but fails when
        # ATR is 16 pips (0.5 x 16 = 8 > 6)
        assert stop_pips_ok(self._cand(sl=1.0994, atr=0.0004), "EURUSD")
        assert not stop_pips_ok(self._cand(sl=1.0994, atr=0.0016), "EURUSD")

    def test_jpy_pip_size(self):
        c = Candidate("TF-H1-DON55", "USDJPY", "BUY", 150.00,
                      149.60, 150.80, 0.08, "1h")  # 40-pip stop, 8-pip ATR
        assert stop_pips_ok(c, "USDJPY")
        c2 = Candidate("TF-H1-DON55", "USDJPY", "BUY", 150.00,
                       149.96, 150.80, 0.08, "1h")  # 4-pip stop
        assert not stop_pips_ok(c2, "USDJPY")
