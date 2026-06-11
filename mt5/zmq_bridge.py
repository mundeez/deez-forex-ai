#!/usr/bin/env python3
"""
ZeroMQ Bridge for MT5 Container
Runs inside Wine Python (where MetaTrader5 works natively).

REQ/REP socket on port 5555: commands (GET_PRICE, GET_CANDLES, etc.)
PUB socket on port 5556: real-time tick streaming
"""
import sys
import time
import json
import threading
import MetaTrader5 as mt5
import zmq

ZMQ_REQ_ADDR = "tcp://0.0.0.0:5555"
ZMQ_PUB_ADDR = "tcp://0.0.0.0:5556"
INIT_TIMEOUT = 5000  # ms

# Map timeframe strings to MT5 constants
TIMEFRAME_MAP = {
    "1m": mt5.TIMEFRAME_M1,
    "5m": mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "30m": mt5.TIMEFRAME_M30,
    "1h": mt5.TIMEFRAME_H1,
    "4h": mt5.TIMEFRAME_H4,
    "1d": mt5.TIMEFRAME_D1,
    "1w": mt5.TIMEFRAME_W1,
    "1mn": mt5.TIMEFRAME_MN1,
}

_mt5_initialized = False


def ensure_mt5():
    """Ensure MT5 is initialized, with timeout and error handling."""
    global _mt5_initialized
    if _mt5_initialized:
        return True
    try:
        info = mt5.terminal_info()
        if info is not None:
            _mt5_initialized = True
            return True
    except Exception:
        pass
    result = mt5.initialize(timeout=INIT_TIMEOUT)
    if result:
        _mt5_initialized = True
        return True
    return False


def handle_get_price(payload):
    symbol = payload.get("symbol", "EURUSD")
    if not ensure_mt5():
        return {"error": "MT5 not initialized — no broker account connected"}
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"error": f"Unable to get price for {symbol}"}
    return {
        "symbol": symbol,
        "bid": round(tick.bid, 5),
        "ask": round(tick.ask, 5),
        "timestamp": int(tick.time_msc),
    }


def handle_get_candles(payload):
    symbol = payload.get("symbol", "EURUSD")
    tf_str = payload.get("timeframe", "1h")
    limit = min(int(payload.get("limit", 500)), 2000)
    tf = TIMEFRAME_MAP.get(tf_str, mt5.TIMEFRAME_H1)
    if not ensure_mt5():
        return {"error": "MT5 not initialized — no broker account connected"}
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, limit)
    if rates is None or len(rates) == 0:
        return {"error": "No candle data available"}
    candles = []
    for r in rates:
        candles.append({
            "timestamp": int(r[0]) * 1000,
            "open": round(float(r[1]), 5),
            "high": round(float(r[2]), 5),
            "low": round(float(r[3]), 5),
            "close": round(float(r[4]), 5),
            "volume": int(r[5]),
        })
    return {"candles": candles}


def handle_get_account(payload):
    if not ensure_mt5():
        return {"error": "MT5 not initialized — no broker account connected"}
    info = mt5.account_info()
    if info is None:
        return {"error": "Unable to get account info"}
    return {
        "balance": round(info.balance, 2),
        "equity": round(info.equity, 2),
        "margin": round(info.margin, 2),
        "free_margin": round(info.margin_free, 2),
        "currency": info.currency,
        "leverage": info.leverage,
    }


def handle_get_positions(payload):
    if not ensure_mt5():
        return {"error": "MT5 not initialized — no broker account connected"}
    positions = mt5.positions_get()
    if positions is None:
        positions = []
    result = []
    for p in positions:
        result.append({
            "ticket": str(p.ticket),
            "symbol": p.symbol,
            "type": "BUY" if p.type == 0 else "SELL",
            "volume": round(p.volume, 2),
            "open_price": round(p.price_open, 5),
            "sl": round(p.sl, 5),
            "tp": round(p.tp, 5),
            "profit": round(p.profit, 2),
        })
    return {"positions": result}


def handle_trade(payload):
    if not ensure_mt5():
        return {"error": "MT5 not initialized — no broker account connected"}
    action_type = payload.get("actionType", "ORDER_TYPE_BUY")
    symbol = payload.get("symbol", "EURUSD")
    volume = float(payload.get("volume", 0.1))
    sl = float(payload.get("stopLoss", 0))
    tp = float(payload.get("takeProfit", 0))
    order_type = mt5.ORDER_TYPE_BUY if action_type == "ORDER_TYPE_BUY" else mt5.ORDER_TYPE_SELL

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"error": "Cannot get price"}
    price = round(tick.ask, 5) if order_type == mt5.ORDER_TYPE_BUY else round(tick.bid, 5)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "deviation": 10,
        "magic": 123456,
        "comment": "deez-forex-ai",
    }
    if sl > 0:
        request["sl"] = sl
    if tp > 0:
        request["tp"] = tp

    result = mt5.order_send(request)
    if result is None:
        return {"error": "OrderSend failed", "result": "failed"}
    return {
        "ticket": str(result.order),
        "volume": round(result.volume, 2),
        "price": round(result.price, 5),
        "result": "done" if result.retcode == 10009 else "failed",
    }


def handle_close(payload):
    if not ensure_mt5():
        return {"error": "MT5 not initialized — no broker account connected"}
    ticket = int(payload.get("ticket", 0))
    if ticket == 0:
        return {"error": "Invalid ticket"}

    position = mt5.positions_get(ticket=ticket)
    if position is None or len(position) == 0:
        return {"error": f"Position {ticket} not found"}

    pos = position[0]
    symbol = pos.symbol
    order_type = pos.type
    volume = pos.volume

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"error": "Cannot get price"}
    price = round(tick.bid, 5) if order_type == 0 else round(tick.ask, 5)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol": symbol,
        "volume": volume,
        "type": mt5.ORDER_TYPE_SELL if order_type == 0 else mt5.ORDER_TYPE_BUY,
        "price": price,
        "deviation": 10,
        "magic": 123456,
        "comment": "deez-forex-ai close",
    }
    result = mt5.order_send(request)
    if result is None:
        return {"error": "OrderSend failed", "result": "failed"}
    return {
        "ticket": str(ticket),
        "result": "done" if result.retcode == 10009 else "failed",
    }


def handle_command(payload):
    action = payload.get("action", "")
    symbol = payload.get("symbol", "EURUSD")

    print(f"[zmq_bridge] Command: {action} Symbol: {symbol}")

    if action == "GET_PRICE":
        return handle_get_price(payload)
    elif action == "GET_CANDLES":
        return handle_get_candles(payload)
    elif action == "GET_ACCOUNT":
        return handle_get_account(payload)
    elif action == "GET_POSITIONS":
        return handle_get_positions(payload)
    elif action == "TRADE":
        return handle_trade(payload)
    elif action == "CLOSE":
        return handle_close(payload)
    else:
        return {"error": f"Unknown action: {action}"}


def rep_loop():
    """REQ/REP socket handler."""
    context = zmq.Context()
    socket = context.socket(zmq.REP)
    socket.bind(ZMQ_REQ_ADDR)
    socket.setsockopt(zmq.RCVTIMEO, 100)
    socket.setsockopt(zmq.SNDTIMEO, 2000)
    print(f"[zmq_bridge] REP socket bound to {ZMQ_REQ_ADDR}")

    while True:
        try:
            msg = socket.recv_string()
            payload = json.loads(msg)
        except zmq.Again:
            continue
        except json.JSONDecodeError:
            socket.send_string(json.dumps({"error": "Invalid JSON"}))
            continue

        try:
            response = handle_command(payload)
        except Exception as e:
            print(f"[zmq_bridge] Error handling command: {e}")
            response = {"error": str(e)}

        try:
            socket.send_string(json.dumps(response))
        except Exception as e:
            print(f"[zmq_bridge] Error sending response: {e}")


def pub_loop():
    """PUB socket tick publisher."""
    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.bind(ZMQ_PUB_ADDR)
    print(f"[zmq_bridge] PUB socket bound to {ZMQ_PUB_ADDR}")

    last_ticks = {}
    while True:
        try:
            if not ensure_mt5():
                time.sleep(5)
                continue
            symbols = ["EURUSD"]
            for symbol in symbols:
                tick = mt5.symbol_info_tick(symbol)
                if tick is None:
                    continue
                tick_key = f"{symbol}:{tick.bid}:{tick.ask}"
                if last_ticks.get(symbol) == tick_key:
                    continue
                last_ticks[symbol] = tick_key
                msg = {
                    "type": "tick",
                    "symbol": symbol,
                    "bid": round(tick.bid, 5),
                    "ask": round(tick.ask, 5),
                    "last": round(tick.last, 5),
                    "volume": int(tick.volume),
                    "timestamp": int(tick.time_msc),
                }
                socket.send_string(json.dumps(msg))
        except Exception as e:
            print(f"[zmq_bridge] Tick publish error: {e}")
        time.sleep(0.1)


def main():
    print("[zmq_bridge] Starting ZeroMQ bridge...")
    rep_thread = threading.Thread(target=rep_loop, daemon=True)
    pub_thread = threading.Thread(target=pub_loop, daemon=True)
    rep_thread.start()
    pub_thread.start()
    print("[zmq_bridge] Both REP and PUB loops running.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[zmq_bridge] Shutting down.")
        mt5.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
