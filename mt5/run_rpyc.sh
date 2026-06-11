#!/bin/bash
export WINEPREFIX=/config/.wine
export WINEDEBUG=-all
export DISPLAY=:99

echo "[rpyc] Waiting for MT5 to be ready..."
for i in $(seq 1 60); do
    MT5_EXE="/config/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
    if [ -f "/config/.wine/drive_c/Program Files/MetaTrader 5/terminal.exe" ]; then
        MT5_EXE="/config/.wine/drive_c/Program Files/MetaTrader 5/terminal.exe"
    fi
    if pgrep -f "$MT5_EXE" > /dev/null 2>&1; then
        echo "[rpyc] MT5 process detected. Waiting 15s for full load..."
        sleep 15
        break
    fi
    sleep 2
done

echo "[rpyc] Starting rpyc server via Wine Python..."
exec wine python /app/rpyc_server.py
