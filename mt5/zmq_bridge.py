#!/usr/bin/env python3
"""
ZMQ Bridge for MT5 running inside Wine.
Uses the MetaTrader5 Python module directly.
"""
import json
import sys
import time
import zmq
import MetaTrader5 as mt5

# --- Configuration ---
ZMQ_HOST = "0.0.0.0"
ZMQ_REQ_PORT = 5555
ZMQ_PUB_PORT = 5556

# --- Timeframe mapping ---
TIMEFRAMES = {
    "1m": mt5.TIMEFRAME_M1,
    "5m": mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "30m": mt5.TIMEFRAME_M30,
    "1h": mt5.TIMEFRAME_H1,
    "4h": mt5.TIMEFRAME_H4,
    "1d": mt5.TIMEFRAME_D1,
    "1w": mt5.TIMEFRAME_W1,
}

def initialize_mt5():
    print("[zmq_bridge] Initializing MetaTrader5...")
    for attempt in range(3):
        if mt5.initialize(timeout=30000):
            print("[zmq_bridge] MT5 initialized successfully")
            info = mt5.terminal_info()
            print(f"[zmq_bridge] Terminal: {info.name} build {info.build}")
            return True
        print(f"[zmq_bridge] MT5 init failed, retrying ({attempt+1}/3)...")
        time.sleep(5)
    print("[zmq_bridge] MT5 init failed after 3 attempts")
    return False

def handle_get_price(symbol):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"error": f"Unable to get price for {symbol}"}
    return {
        "symbol": symbol,
        "bid": tick.bid,
        "ask": tick.ask,
        "timestamp": int(tick.time_msc),
    }

def handle_get_candles(symbol, timeframe_str, limit):
    tf = TIMEFRAMES.get(timeframe_str, mt5.TIMEFRAME_H1)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, limit)
    if rates is None or len(rates) == 0:
        return {"error": "No candle data available"}
    candles = []
    for r in rates:
        candles.append({
            "timestamp": int(r[0]) * 1000,
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": int(r[5]),
        })
    return {"candles": candles}

def handle_get_account():
    info = mt5.account_info()
    if info is None:
        return {"error": "Unable to get account info"}
    return {
        "balance": info.balance,
        "equity": info.equity,
        "margin": info.margin,
        "free_margin": info.margin_free,
        "currency": info.currency,
        "leverage": info.leverage,
    }

def handle_get_positions():
    positions = mt5.positions_get()
    if positions is None:
        return {"positions": []}
    result = []
    for p in positions:
        result.append({
            "ticket": p.ticket,
            "symbol": p.symbol,
            "type": "BUY" if p.type == 0 else "SELL",
            "volume": p.volume,
            "open_price": p.price_open,
            "sl": p.sl,
            "tp": p.tp,
            "profit": p.profit,
        })
    return {"positions": result}

def handle_trade(order):
    action_type = order.get("actionType", "ORDER_TYPE_BUY")
    symbol = order.get("symbol", "EURUSD")
    volume = float(order.get("volume", 0.01))
    sl = float(order.get("stopLoss", 0))
    tp = float(order.get("takeProfit", 0))
    
    order_type = mt5.ORDER_TYPE_BUY if action_type == "ORDER_TYPE_BUY" else mt5.ORDER_TYPE_SELL
    
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"error": "Cannot get price", "result": "failed"}
    
    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    
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
        return {"error": f"OrderSend failed: {mt5.last_error()}", "result": "failed"}
    return {
        "ticket": result.order,
        "volume": result.volume,
        "price": result.price,
        "result": "done",
    }

def handle_close(order):
    ticket = int(order.get("ticket", 0))
    if ticket == 0:
        return {"error": "Invalid ticket"}
    
    position = mt5.positions_get(ticket=ticket)
    if position is None or len(position) == 0:
        return {"error": "Position not found"}
    
    p = position[0]
    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        return {"error": "Cannot get price"}
    
    price = tick.bid if p.type == 0 else tick.ask
    deviation = 10
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": p.symbol,
        "volume": p.volume,
        "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
        "position": ticket,
        "price": price,
        "deviation": deviation,
        "magic": 123456,
        "comment": "deez-forex-ai close",
    }
    
    result = mt5.order_send(request)
    if result is None:
        return {"error": f"Close failed: {mt5.last_error()}", "result": "failed"}
    return {
        "ticket": ticket,
        "result": "done",
    }

def handle_command(payload):
    action = payload.get("action", "")
    symbol = payload.get("symbol", "EURUSD")
    
    if action == "GET_PRICE":
        return handle_get_price(symbol)
    elif action == "GET_CANDLES":
        return handle_get_candles(symbol, payload.get("timeframe", "1h"), int(payload.get("limit", 500)))
    elif action == "GET_ACCOUNT":
        return handle_get_account()
    elif action == "GET_POSITIONS":
        return handle_get_positions()
    elif action == "TRADE":
        return handle_trade(payload)
    elif action == "CLOSE":
        return handle_close(payload)
    else:
        return {"error": f"Unknown action: {action}"}

def main():
    if not initialize_mt5():
        sys.exit(1)
    
    ctx = zmq.Context()
    rep_sock = ctx.socket(zmq.REP)
    rep_addr = f"tcp://{ZMQ_HOST}:{ZMQ_REQ_PORT}"
    rep_sock.bind(rep_addr)
    print(f"[zmq_bridge] REP socket bound to {rep_addr}")
    
    pub_sock = ctx.socket(zmq.PUB)
    pub_addr = f"tcp://{ZMQ_HOST}:{ZMQ_PUB_PORT}"
    pub_sock.bind(pub_addr)
    print(f"[zmq_bridge] PUB socket bound to {pub_addr}")
    
    print("[zmq_bridge] Ready. Waiting for requests...")
    
    try:
        while True:
            try:
                msg = rep_sock.recv_string(zmq.NOBLOCK)
                payload = json.loads(msg)
                print(f"[zmq_bridge] Received: {payload.get('action')}")
                response = handle_command(payload)
                rep_sock.send_string(json.dumps(response))
            except zmq.Again:
                pass
            
            # Publish tick data periodically
            try:
                tick = mt5.symbol_info_tick("EURUSD")
                if tick:
                    pub_sock.send_string(json.dumps({
                        "symbol": "EURUSD",
                        "bid": tick.bid,
                        "ask": tick.ask,
                        "timestamp": int(tick.time_msc),
                    }), zmq.NOBLOCK)
            except zmq.Again:
                pass
            
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("[zmq_bridge] Shutting down...")
    finally:
        mt5.shutdown()
        rep_sock.close()
        pub_sock.close()
        ctx.term()

if __name__ == "__main__":
    main()
