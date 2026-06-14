#!/bin/bash
# Start Redis Tick Publisher in Linux Python
set -e

echo "[run_redis_publisher] Waiting for RPyC SlaveService (port 18813)..."
for i in $(seq 1 120); do
    if nc -z 127.0.0.1 18813 2>/dev/null; then
        echo "[run_redis_publisher] SlaveService detected. Starting publisher..."
        sleep 5
        break
    fi
    sleep 2
done

echo "[run_redis_publisher] Starting Redis Tick Publisher..."
export REDIS_URL="${REDIS_URL:-redis://redis:6379/0}"
export RPYC_HOST="${RPYC_HOST:-127.0.0.1}"
export RPYC_PORT="${RPYC_PORT:-18813}"
export SYMBOLS="${SYMBOLS:-EURUSD}"
export INTERVAL_MS="${INTERVAL_MS:-500}"
exec python3 /app/redis_tick_publisher.py
