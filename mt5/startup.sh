#!/bin/bash
set -e

# =============================================================================
# MT5 Container Entrypoint — Proven approach from gmag11/metatrader5_vnc
# =============================================================================

INIT_MARKER="/config/.mt5_initialized"

# Configuration
mt5file="/config/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
WINEPREFIX="/config/.wine"
WINEDEBUG="-all"
wine_executable="wine"
metatrader_version="5.0.37"
mono_url="https://dl.winehq.org/wine/wine-mono/10.3.0/wine-mono-10.3.0-x86.msi"
python_url="https://www.python.org/ftp/python/3.9.13/python-3.9.13.exe"
mt5setup_url="https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"

export WINEPREFIX

# Ensure Wine prefix directory exists
mkdir -p "$WINEPREFIX/drive_c"

# Clean up stale Xvfb lock files from previous container restarts
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

# Start persistent Xvfb *before* any Wine commands
if ! pgrep -f "Xvfb :99" > /dev/null 2>&1; then
    echo "[startup] Starting persistent Xvfb on :99 ..."
    Xvfb :99 -screen 0 1024x768x24 +extension GLX &
    sleep 2
    echo "[startup] Xvfb started"
fi
export DISPLAY=:99

# Helper: find python.exe in Wine prefix
find_wine_python() {
    find "$WINEPREFIX" -name "python.exe" 2>/dev/null | head -1
}

if [ ! -f "$INIT_MARKER" ]; then
    echo "[startup] First run — setting up Wine + MT5 ..."

    # 1. Install Wine Mono if not present
    if [ ! -e "$WINEPREFIX/drive_c/windows/mono" ]; then
        echo "[startup] [1/7] Installing Wine Mono..."
        curl -L -o "$WINEPREFIX/drive_c/mono.msi" "$mono_url"
        WINEDLLOVERRIDES=mscoree=d $wine_executable msiexec /i "$WINEPREFIX/drive_c/mono.msi" /qn
        rm -f "$WINEPREFIX/drive_c/mono.msi"
        echo "[startup] [1/7] Mono installed."
    else
        echo "[startup] [1/7] Mono already installed."
    fi

    # 2. Set Windows 10 mode in Wine
    echo "[startup] [2/7] Setting Windows 10 mode..."
    $wine_executable reg add "HKEY_CURRENT_USER\\Software\\Wine" /v Version /t REG_SZ /d "win10" /f

    # 3. Install MetaTrader 5
    if [ -e "$mt5file" ]; then
        echo "[startup] [3/7] MT5 already installed."
    else
        echo "[startup] [3/7] Downloading MT5 installer..."
        curl -L -o "$WINEPREFIX/drive_c/mt5setup.exe" "$mt5setup_url"
        echo "[startup] [3/7] Installing MetaTrader 5 (this may take a few minutes)..."
        $wine_executable "$WINEPREFIX/drive_c/mt5setup.exe" "/auto" &
        MT5_INSTALL_PID=$!
        # Wait for the installer to finish (up to 10 minutes)
        for i in $(seq 1 600); do
            if ! kill -0 $MT5_INSTALL_PID 2>/dev/null; then
                echo "[startup] [3/7] Installer process finished."
                break
            fi
            sleep 1
        done
        if kill -0 $MT5_INSTALL_PID 2>/dev/null; then
            echo "[startup] [3/7] MT5 installer still running after 10 min, killing..."
            kill $MT5_INSTALL_PID 2>/dev/null || true
            wait $MT5_INSTALL_PID 2>/dev/null || true
        fi
        rm -f "$WINEPREFIX/drive_c/mt5setup.exe"
    fi

    # 4. Verify MT5 installation
    if [ -e "$mt5file" ]; then
        echo "[startup] [4/7] MT5 installed."
    else
        echo "[startup] [4/7] WARNING: MT5 installation may have failed. Checking common paths..."
        for path in \
            "$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe" \
            "$WINEPREFIX/drive_c/Program Files (x86)/MetaTrader 5/terminal.exe" \
            "$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal.exe"; do
            if [ -e "$path" ]; then
                echo "[startup] [4/7] Found MT5 at $path"
                mt5file="$path"
                break
            fi
        done
        if [ ! -e "$mt5file" ]; then
            echo "[startup] [4/7] ERROR: MT5 installation failed."
            exit 1
        fi
    fi

    # 5. Install Python in Wine
    WINE_PYTHON=$(find_wine_python)
    if [ -n "$WINE_PYTHON" ]; then
        echo "[startup] [5/7] Python already in Wine at $WINE_PYTHON."
    else
        echo "[startup] [5/7] Installing Python in Wine..."
        curl -L "$python_url" -o /tmp/python-installer.exe
        # Run installer and wait for it to finish (up to 5 minutes)
        $wine_executable /tmp/python-installer.exe /quiet InstallAllUsers=1 PrependPath=1 &
        PYTHON_PID=$!
        for i in $(seq 1 300); do
            if ! kill -0 $PYTHON_PID 2>/dev/null; then
                echo "[startup] [5/7] Python installer finished."
                break
            fi
            sleep 1
        done
        if kill -0 $PYTHON_PID 2>/dev/null; then
            echo "[startup] [5/7] Python installer still running after 5 min, killing..."
            kill $PYTHON_PID 2>/dev/null || true
            wait $PYTHON_PID 2>/dev/null || true
        fi
        rm -f /tmp/python-installer.exe
        WINE_PYTHON=$(find_wine_python)
        if [ -z "$WINE_PYTHON" ]; then
            echo "[startup] [5/7] ERROR: Python installation failed."
            exit 1
        fi
        echo "[startup] [5/7] Python installed in Wine at $WINE_PYTHON."
    fi

    # 6. Install Python libraries in Wine
    echo "[startup] [6/7] Installing MetaTrader5 + mt5linux + rpyc + pyzmq in Wine Python..."
    $wine_executable "$WINE_PYTHON" -m pip install --upgrade --no-cache-dir pip || true
    $wine_executable "$WINE_PYTHON" -m pip install --no-cache-dir "numpy<2" || true
    $wine_executable "$WINE_PYTHON" -m pip install --no-cache-dir "MetaTrader5==$metatrader_version" || true
    $wine_executable "$WINE_PYTHON" -m pip install --no-cache-dir "mt5linux>=0.1.9" || true
    $wine_executable "$WINE_PYTHON" -m pip install --no-cache-dir rpyc || true
    $wine_executable "$WINE_PYTHON" -m pip install --no-cache-dir pyzmq || true
    echo "[startup] [6/7] Wine Python libraries installed."

    # 7. Install mt5linux + rpyc in Linux Python
    echo "[startup] [7/7] Installing mt5linux + rpyc in Linux Python..."
    pip3 install --break-system-packages --no-cache-dir rpyc==5.2.3 plumbum==1.7.0 pyparsing==3.2.3 numpy || true
    pip3 install --break-system-packages --no-cache-dir --no-deps mt5linux || true
    echo "[startup] [7/7] Linux Python libraries installed."

    touch "$INIT_MARKER"
    echo "[startup] Initialization complete."
else
    echo "[startup] Already initialized — skipping setup."
fi

echo "[startup] Starting supervisor..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
