#!/usr/bin/env python3
"""
MT5 ZMQ Bridge — Milestone 1 stub.
Connects to Wine-side MT5 via rpyc and verifies connectivity.
Full ZMQ server implementation will be added in Milestone 2.
"""
import sys


def main():
    print("[zmq_bridge] Milestone 1 stub — verifying MT5 connectivity...")
    try:
        import rpyc
        conn = rpyc.classic.connect("localhost", 18812, timeout=10)
        conn.execute("import MetaTrader5 as mt5")
        info = conn.eval("mt5.terminal_info()")
        if info:
            print(f"[zmq_bridge] MT5 connected — {info}")
        else:
            print("[zmq_bridge] MT5 terminal_info returned None")
        conn.close()
    except Exception as e:
        print(f"[zmq_bridge] ERROR: {e}")
        sys.exit(1)
    print("[zmq_bridge] Stub complete. Keeping alive for supervisor...")
    # Keep running so supervisor doesn't restart us
    import time
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
