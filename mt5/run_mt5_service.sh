#!/bin/bash
# Start custom RPyC MT5Service inside Wine Python
set -e
export WINEPREFIX=/config/.wine
export WINEDEBUG=-all
export DISPLAY=:99

echo "[run_mt5_service] Waiting for MT5 terminal..."
for i in $(seq 1 120); do
    MT5_EXE="/config/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
    if [ -f "/config/.wine/drive_c/Program Files/MetaTrader 5/terminal.exe" ]; then
        MT5_EXE="/config/.wine/drive_c/Program Files/MetaTrader 5/terminal.exe"
    fi
    if pgrep -f "$MT5_EXE" > /dev/null 2>&1; then
        echo "[run_mt5_service] MT5 detected. Waiting 20s for full load..."
        sleep 20
        break
    fi
    sleep 2
done

echo "[run_mt5_service] Starting MT5Service via Wine Python..."
exec wine python /app/mt5_service.py
