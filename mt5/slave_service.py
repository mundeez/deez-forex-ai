#!/usr/bin/env python3
"""
RPyC SlaveService for mt5linux compatibility and debug access.
Runs inside Wine Python alongside MT5Service.
Uses generic SlaveService (arbitrary code execution via eval/execute).
This is for mt5linux library compatibility and remote debugging.

SECURITY NOTE: Only exposed on internal Docker network (port 18813).
Never exposed externally.
"""
import sys
import rpyc
from rpyc.utils.server import ThreadedServer


def main():
    host = "0.0.0.0"
    port = 18813
    print(f"[slave_service] Starting RPyC SlaveService on {host}:{port}", flush=True)
    try:
        t = ThreadedServer(
            rpyc.SlaveService,
            hostname=host,
            port=port,
            reuse_addr=True,
        )
        print("[slave_service] SlaveService ready. Waiting for connections...", flush=True)
        t.start()
    except KeyboardInterrupt:
        print("[slave_service] Shutting down.", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"[slave_service] ERROR: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
