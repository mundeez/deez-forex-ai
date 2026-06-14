#!/usr/bin/env python
"""
Wine-side rpyc server for MT5 Linux bridge.
Runs inside Wine Python (where MetaTrader5 package works).

NOTE: This file now starts the PRIMARY MT5Service on port 18812.
The legacy SlaveService for mt5linux compatibility has been moved to
slave_service.py running on port 18813.

Exposes a custom MT5Service with typed, safe methods for the backend.
"""
import sys
from mt5_service import MT5Service
from rpyc.utils.server import ThreadedServer


def main():
    host = "0.0.0.0"
    port = 18812
    print(f"[rpyc_server] Starting RPyC MT5Service on {host}:{port}", flush=True)
    try:
        t = ThreadedServer(
            MT5Service,
            hostname=host,
            port=port,
            reuse_addr=True,
            protocol_config={"allow_public_attrs": True},
        )
        print("[rpyc_server] MT5Service started. Waiting for connections...", flush=True)
        t.start()
    except KeyboardInterrupt:
        print("[rpyc_server] Shutting down.", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"[rpyc_server] ERROR: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
