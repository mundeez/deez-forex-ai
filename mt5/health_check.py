#!/usr/bin/env python3
"""
Docker HEALTHCHECK probe for the MT5 container.
Verifies that the Wine-side rpyc server is reachable and MT5 module loads.
"""
import sys
import socket


def check():
    # Verify rpyc server is listening on port 18812
    try:
        sock = socket.create_connection(("localhost", 18812), timeout=5)
        sock.close()
    except Exception as e:
        print(f"[health] RPyC server not reachable on port 18812: {e}")
        return 1

    # Verify MT5 API responds through rpyc
    try:
        import rpyc
        conn = rpyc.classic.connect("localhost", 18812)
        conn.execute("import MetaTrader5 as mt5")
        print("[health] MT5 OK — module imports successfully")
        conn.close()
        return 0
    except Exception as e:
        print(f"[health] MT5 not ready: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(check())
