#!/usr/bin/env python3
"""
Redis Tick Publisher for deez-forex-ai MT5 container
Runs in Linux Python (NOT Wine Python).

Uses mt5linux library to connect to Wine Python's SlaveService (port 18813),
polls tick data from MetaTrader5, and publishes to Redis pub/sub channels.

Each tick is published to: mt5:ticks:{symbol}
Format: JSON {"type":"tick","symbol":"EURUSD","bid":1.08543,...}

Usage:
    python3 redis_tick_publisher.py

Environment:
    REDIS_URL   Redis connection URL (default: redis://redis:6379/0)
    RPYC_HOST   RPyC host for SlaveService (default: 127.0.0.1)
    RPYC_PORT   RPyC port for SlaveService (default: 18813)
    SYMBOLS     Comma-separated symbols to track (default: EURUSD)
    INTERVAL_MS Poll interval in ms (default: 500)
"""
import os
import sys
import time
import json
import logging
import traceback

logging.basicConfig(
    level=logging.INFO,
    format="[redis_tick_publisher] %(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("redis_tick_publisher")

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
try:
    import redis
except ImportError:
    logger.critical("redis package not installed. Install with: pip install redis")
    sys.exit(1)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
RPYC_HOST = os.environ.get("RPYC_HOST", "127.0.0.1")
RPYC_PORT = int(os.environ.get("RPYC_PORT", "18813"))
SYMBOLS = [s.strip() for s in os.environ.get("SYMBOLS", "EURUSD").split(",")]
INTERVAL_MS = int(os.environ.get("INTERVAL_MS", "500"))
INTERVAL_S = INTERVAL_MS / 1000.0


def connect_redis():
    """Create Redis connection from URL."""
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
        r.ping()
        logger.info("Redis connected: %s", REDIS_URL)
        return r
    except Exception as e:
        logger.error("Redis connection failed: %s", e)
        return None


def connect_mt5():
    """Connect to MT5 via mt5linux -> Wine Python SlaveService."""
    try:
        import mt5linux
        mt5 = mt5linux.MetaTrader5(host=RPYC_HOST, port=RPYC_PORT)
        # Quick test
        info = mt5.terminal_info()
        if info and getattr(info, "connected", False):
            logger.info("MT5 connected via mt5linux (RPyC %s:%d)", RPYC_HOST, RPYC_PORT)
            return mt5
        logger.warning("MT5 terminal_info returned: %s", info)
        return mt5
    except Exception as e:
        logger.error("MT5/mt5linux connection failed: %s", e)
        return None


def publish_tick(redis_conn, symbol, tick):
    """Publish a tick to Redis pub/sub."""
    channel = f"mt5:ticks:{symbol}"
    try:
        redis_conn.publish(channel, json.dumps(tick))
    except Exception as e:
        logger.warning("Failed to publish tick to %s: %s", channel, e)


def main():
    logger.info("Starting Redis Tick Publisher")
    logger.info("  Symbols: %s", SYMBOLS)
    logger.info("  Redis: %s", REDIS_URL)
    logger.info("  RPyC: %s:%d", RPYC_HOST, RPYC_PORT)
    logger.info("  Interval: %.0f ms", INTERVAL_MS)

    redis_conn = None
    mt5 = None
    last_ticks = {}

    while True:
        try:
            if redis_conn is None:
                redis_conn = connect_redis()
                if redis_conn is None:
                    time.sleep(5)
                    continue

            if mt5 is None:
                mt5 = connect_mt5()
                if mt5 is None:
                    time.sleep(5)
                    continue

            for symbol in SYMBOLS:
                try:
                    tick = mt5.symbol_info_tick(symbol)
                    if tick is None:
                        continue
                    tick_key = f"{symbol}:{tick.bid}:{tick.ask}:{tick.time_msc}"
                    if last_ticks.get(symbol) == tick_key:
                        continue
                    last_ticks[symbol] = tick_key

                    msg = {
                        "type": "tick",
                        "symbol": symbol,
                        "bid": round(float(tick.bid), 5),
                        "ask": round(float(tick.ask), 5),
                        "last": round(float(tick.last), 5),
                        "volume": int(tick.volume),
                        "timestamp": int(tick.time_msc),
                    }
                    publish_tick(redis_conn, symbol, msg)
                except Exception as e:
                    logger.warning("Error getting tick for %s: %s", symbol, e)
                    if "Connection" in str(e) or "closed" in str(e):
                        mt5 = None
                        break

            time.sleep(INTERVAL_S)

        except KeyboardInterrupt:
            logger.info("Shutting down")
            break
        except Exception as e:
            logger.error("Unexpected error: %s\n%s", e, traceback.format_exc())
            time.sleep(5)

    if redis_conn:
        redis_conn.close()
    logger.info("Stopped")


if __name__ == "__main__":
    main()
