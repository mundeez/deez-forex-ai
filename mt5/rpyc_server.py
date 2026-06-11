#!/usr/bin/env python
"""
Wine-side rpyc server for MT5 Linux bridge.
Runs inside Wine Python (where MetaTrader5 package works).
Exposes a classic rpyc server on port 18812.
"""
import sys
import rpyc
from rpyc.utils.server import ThreadedServer


def main():
    host = "0.0.0.0"
    port = 18812
    print(f"[rpyc_server] Starting rpyc classic server on {host}:{port}", flush=True)

    try:
        t = ThreadedServer(
            rpyc.SlaveService,
            hostname=host,
            port=port,
            reuse_addr=True,
        )
        print("[rpyc_server] Server started. Waiting for connections...", flush=True)
        t.start()
    except KeyboardInterrupt:
        print("[rpyc_server] Shutting down.", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"[rpyc_server] ERROR: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
