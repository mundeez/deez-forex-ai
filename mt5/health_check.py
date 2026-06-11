#!/usr/bin/env python3
"""
Docker HEALTHCHECK probe for the MT5 container.
Verifies that ZMQ bridge ports are listening and responsive.
Does NOT require an active MT5 broker account.
"""
import sys
import socket
import json


def check():
    # Verify ZMQ REP port is listening
    try:
        sock = socket.create_connection(("localhost", 5555), timeout=5)
        sock.close()
    except Exception as e:
        print(f"[health] ZMQ REP not reachable on port 5555: {e}")
        return 1

    # Verify ZMQ PUB port is listening
    try:
        sock = socket.create_connection(("localhost", 5556), timeout=5)
        sock.close()
    except Exception as e:
        print(f"[health] ZMQ PUB not reachable on port 5556: {e}")
        return 1

    # Verify ZMQ bridge responds to a probe (even if MT5 is not initialized)
    try:
        import zmq
        ctx = zmq.Context()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.RCVTIMEO, 20000)  # 20s — allows for mt5.initialize timeout
        sock.setsockopt(zmq.SNDTIMEO, 5000)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect("tcp://localhost:5555")
        sock.send_string(json.dumps({"action": "GET_PRICE", "symbol": "EURUSD"}))
        resp = sock.recv_string()
        data = json.loads(resp)
        # Either success or "MT5 not initialized" is acceptable
        if "error" in data and "not initialized" not in data.get("error", ""):
            print(f"[health] ZMQ probe error: {data['error']}")
            return 1
        print("[health] ZMQ bridge OK")
        sock.close()
        ctx.term()
        return 0
    except Exception as e:
        print(f"[health] ZMQ probe failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(check())
