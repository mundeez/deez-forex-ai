#!/usr/bin/env python3
"""Health check for MT5 container with ZMQ bridge."""
import subprocess
import sys
import zmq
import json

def check_process(name):
    try:
        subprocess.run(["pgrep", "-f", name], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False

def main():
    # Check MT5 terminal
    if not check_process("terminal64.exe"):
        print("FAIL: MT5 terminal not running")
        sys.exit(1)

    # Check KasmVNC
    if not check_process("Xvnc :99"):
        print("FAIL: KasmVNC not running")
        sys.exit(1)

    # Check if ZeroMQ bridge is responding
    try:
        ctx = zmq.Context()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.RCVTIMEO, 5000)
        sock.setsockopt(zmq.SNDTIMEO, 5000)
        sock.connect("tcp://127.0.0.1:5555")
        sock.send_string(json.dumps({"action": "GET_ACCOUNT"}))
        resp = sock.recv_string()
        data = json.loads(resp)
        if "error" in data and data["error"]:
            print(f"FAIL: ZMQ bridge error: {data[error]}")
            sys.exit(1)
        print("OK: MT5 terminal + KasmVNC + ZMQ bridge responding")
        sys.exit(0)
    except zmq.Again:
        print("FAIL: ZMQ bridge timeout")
        sys.exit(1)
    except Exception as e:
        print(f"FAIL: ZMQ bridge error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
