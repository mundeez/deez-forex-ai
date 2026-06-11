#!/bin/bash
export WINEPREFIX=/config/.wine
export WINEDEBUG=-all
export DISPLAY=:99

MT5_EXE="/config/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ ! -f "$MT5_EXE" ]; then
    MT5_EXE="/config/.wine/drive_c/Program Files/MetaTrader 5/terminal.exe"
fi
if [ ! -f "$MT5_EXE" ]; then
    echo "ERROR: terminal64.exe not found"
    sleep 10
    exit 1
fi

echo "[mt5_terminal] Starting MT5: $MT5_EXE"
exec wine "$MT5_EXE" /portable
