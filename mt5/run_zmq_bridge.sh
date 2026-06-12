#!/bin/bash
export WINEPREFIX=/config/.wine
export DISPLAY=:99
cd /app
exec wine64 "/config/.wine/drive_c/Program Files (x86)/Python39-32/python.exe" /app/zmq_bridge.py
