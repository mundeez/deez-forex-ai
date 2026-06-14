#!/usr/bin/env python3
"""Fast health check for MT5 container — must complete within Docker's timeout."""

import subprocess
import sys
import socket


def check_process(name):
    try:
        subprocess.run(["pgrep", "-f", name], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False


def check_port(host, port, timeout=2):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.close()
        return True
    except Exception:
        return False


def main():
    # Fast process checks
    mt5_running = check_process("terminal64.exe") or check_process("terminal.exe")
    vnc_running = check_process("Xvnc :99")
    rpyc_listening = check_port("127.0.0.1", 18812)

    if mt5_running and vnc_running:
        if rpyc_listening:
            print("OK: MT5 terminal + KasmVNC + RPyC running")
            sys.exit(0)
        else:
            print("OK: MT5 terminal + KasmVNC running (RPyC not yet listening)")
            sys.exit(0)
    else:
        print(f"FAIL: MT5={mt5_running} VNC={vnc_running} RPyC={rpyc_listening}")
        sys.exit(1)


if __name__ == "__main__":
    main()
