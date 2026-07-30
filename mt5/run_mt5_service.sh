#!/bin/bash
set -e
export WINEPREFIX=/config/.wine
export WINEDEBUG=-all
export DISPLAY=:99

# Source credentials from persistent config
if [ -f /config/mt5_credentials.sh ]; then
    echo "[run_mt5_service] Loading credentials from /config/mt5_credentials.sh"
    source /config/mt5_credentials.sh
fi

export MT5_PATH="C:\\Program Files\\MetaTrader 5\\terminal64.exe"

echo "[run_mt5_service] Starting MT5Service (login=$MT5_LOGIN server=$MT5_SERVER)..."
exec wine python /app/mt5_service.py
