#!/usr/bin/env python3
"""
Custom RPyC MT5 Service for deez-forex-ai
Runs inside Wine Python (where MetaTrader5 package works natively).
Exposes a typed, safe API surface for the backend to call.
"""
import os
import sys
import time
import threading
import logging
import rpyc
from rpyc.utils.server import ThreadedServer

logging.basicConfig(
    level=logging.INFO,
    format="[mt5_service] %(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("mt5_service")

try:
    import MetaTrader5 as mt5
    logger.info("MetaTrader5 imported (v%s)", mt5.__version__)
except ImportError:
    logger.critical("MetaTrader5 not available")
    sys.exit(1)

_mt5_lock = threading.Lock()
_mt5_initialized = False
_last_init_attempt = 0.0
_INIT_RETRY_INTERVAL = 30
INIT_TIMEOUT = 5000

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


def _ensure_mt5(login: int = None, password: str = None, server: str = None) -> bool:
    global _mt5_initialized, _last_init_attempt
    with _mt5_lock:
        if _mt5_initialized:
            return True
        now = time.time()
        if now - _last_init_attempt < _INIT_RETRY_INTERVAL:
            return False
        _last_init_attempt = now
        try:
            if mt5.terminal_info() is not None:
                _mt5_initialized = True
                return True
        except Exception:
            pass
        path = os.environ.get("MT5_PATH", "")
        init_kwargs = {"timeout": 60000}
        if path:
            init_kwargs["path"] = path
            logger.info("MT5 init with path: %s", path)
        if login and password and server:
            init_kwargs["login"] = login
            init_kwargs["password"] = password
            init_kwargs["server"] = server
            logger.info("MT5 init with login %s server %s", login, server)
        else:
            login_env = os.environ.get("MT5_LOGIN")
            password_env = os.environ.get("MT5_PASSWORD")
            server_env = os.environ.get("MT5_SERVER")
            if login_env and password_env and server_env:
                init_kwargs["login"] = int(login_env)
                init_kwargs["password"] = password_env
                init_kwargs["server"] = server_env
                logger.info("MT5 init with env login %s server %s", login_env, server_env)
        if mt5.initialize(**init_kwargs):
            _mt5_initialized = True
            logger.info("MT5 initialized")
            return True
        logger.warning("MT5 init failed: %s", mt5.last_error())
        return False


class MT5Service(rpyc.Service):
    def exposed_get_price(self, symbol: str = "EURUSD") -> dict:
        if not _ensure_mt5():
            return {"error": "MT5 not initialized"}
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"error": f"Cannot get price for {symbol}"}
        return {
            "symbol": symbol,
            "bid": round(tick.bid, 5),
            "ask": round(tick.ask, 5),
            "last": round(tick.last, 5),
            "timestamp": int(tick.time_msc),
        }

    def exposed_get_candles(self, symbol: str = "EURUSD", timeframe: str = "1h", limit: int = 500) -> dict:
        if not _ensure_mt5():
            return {"error": "MT5 not initialized"}
        tf = TIMEFRAME_MAP.get(timeframe, mt5.TIMEFRAME_H1)
        limit = max(1, min(int(limit), 2000))
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

    def exposed_get_symbols(self, group: str = "") -> dict:
        if not _ensure_mt5():
            return {"error": "MT5 not initialized"}
        syms = mt5.symbols_get(group=group) if group else mt5.symbols_get()
        if syms is None:
            return {"symbols": []}
        out = []
        for s in syms:
            out.append({
                "name": s.name,
                "description": s.description,
                "currency_base": s.currency_base,
                "currency_profit": s.currency_profit,
                "digits": s.digits,
            })
        return {"symbols": out}

    def exposed_get_account(self) -> dict:
        if not _ensure_mt5():
            return {"error": "MT5 not initialized"}
        info = mt5.account_info()
        if info is None:
            return {"error": "Cannot get account info"}
        return {
            "balance": round(info.balance, 2),
            "equity": round(info.equity, 2),
            "margin": round(info.margin, 2),
            "free_margin": round(info.margin_free, 2),
            "currency": info.currency,
            "leverage": info.leverage,
            "login": info.login,
            "server": info.server,
        }

    def exposed_get_positions(self) -> dict:
        if not _ensure_mt5():
            return {"error": "MT5 not initialized"}
        pos = mt5.positions_get()
        if pos is None:
            pos = []
        out = []
        for p in pos:
            out.append({
                "ticket": str(p.ticket),
                "symbol": p.symbol,
                "type": "BUY" if p.type == 0 else "SELL",
                "volume": round(p.volume, 2),
                "open_price": round(p.price_open, 5),
                "sl": round(p.sl, 5),
                "tp": round(p.tp, 5),
                "profit": round(p.profit, 2),
                "swap": round(p.swap, 2),
                "time": str(p.time),
            })
        return {"positions": out}

    def exposed_get_orders(self) -> dict:
        if not _ensure_mt5():
            return {"error": "MT5 not initialized"}
        orders = mt5.orders_get()
        if orders is None:
            orders = []
        out = []
        for o in orders:
            out.append({
                "ticket": str(o.ticket),
                "symbol": o.symbol,
                "type": str(o.type),
                "volume": round(o.volume_current, 2),
                "price": round(o.price_open, 5),
                "sl": round(o.sl, 5),
                "tp": round(o.tp, 5),
                "time_setup": str(o.time_setup),
            })
        return {"orders": out}

    def exposed_place_trade(self, order: dict) -> dict:
        if not _ensure_mt5():
            return {"error": "MT5 not initialized"}
        action_type = order.get("actionType", "ORDER_TYPE_BUY")
        symbol = order.get("symbol", "EURUSD")
        volume = float(order.get("volume", 0.1))
        sl = float(order.get("stopLoss", 0))
        tp = float(order.get("takeProfit", 0))
        magic = int(order.get("magic", 123456))
        comment = order.get("comment", "deez-forex-ai")
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
            "magic": magic,
            "comment": comment,
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
            "retcode": result.retcode,
        }

    def exposed_close_position(self, ticket: int) -> dict:
        if not _ensure_mt5():
            return {"error": "MT5 not initialized"}
        if ticket == 0:
            return {"error": "Invalid ticket"}
        pos = mt5.positions_get(ticket=ticket)
        if not pos or len(pos) == 0:
            return {"error": f"Position {ticket} not found"}
        p = pos[0]
        symbol = p.symbol
        order_type = p.type
        volume = p.volume
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
            "retcode": result.retcode,
        }

    def exposed_modify_position(self, ticket: int, sl: float = None, tp: float = None) -> dict:
        if not _ensure_mt5():
            return {"error": "MT5 not initialized"}
        pos = mt5.positions_get(ticket=ticket)
        if not pos or len(pos) == 0:
            return {"error": f"Position {ticket} not found"}
        p = pos[0]
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": p.symbol,
            "sl": round(sl, 5) if sl is not None else p.sl,
            "tp": round(tp, 5) if tp is not None else p.tp,
        }
        result = mt5.order_send(request)
        if result is None:
            return {"error": "OrderSend failed", "result": "failed"}
        return {
            "ticket": str(ticket),
            "result": "done" if result.retcode == 10009 else "failed",
            "retcode": result.retcode,
        }

    def exposed_get_history_deals(self, date_from: str = "", date_to: str = "", group: str = "") -> dict:
        if not _ensure_mt5():
            return {"error": "MT5 not initialized"}
        import datetime
        df = datetime.datetime.strptime(date_from, "%Y-%m-%d") if date_from else None
        dt = datetime.datetime.strptime(date_to, "%Y-%m-%d") if date_to else None
        if df and dt:
            deals = mt5.history_deals_get(df, dt, group=group)
        elif df:
            deals = mt5.history_deals_get(df, group=group)
        else:
            deals = mt5.history_deals_get(0, group=group)
        if deals is None:
            return {"deals": []}
        out = []
        for d in deals:
            out.append({
                "ticket": str(d.ticket),
                "order": str(d.order),
                "time": str(d.time),
                "type": str(d.type),
                "entry": str(d.entry),
                "symbol": d.symbol,
                "volume": round(d.volume, 2),
                "price": round(d.price, 5),
                "profit": round(d.profit, 2),
            })
        return {"deals": out}

    def exposed_get_history_orders(self, date_from: str = "", date_to: str = "") -> dict:
        if not _ensure_mt5():
            return {"error": "MT5 not initialized"}
        import datetime
        df = datetime.datetime.strptime(date_from, "%Y-%m-%d") if date_from else None
        dt = datetime.datetime.strptime(date_to, "%Y-%m-%d") if date_to else None
        if df and dt:
            orders = mt5.history_orders_get(df, dt)
        elif df:
            orders = mt5.history_orders_get(df)
        else:
            orders = mt5.history_orders_get(0)
        if orders is None:
            return {"orders": []}
        out = []
        for o in orders:
            out.append({
                "ticket": str(o.ticket),
                "symbol": o.symbol,
                "type": str(o.type),
                "volume": round(o.volume_initial, 2),
                "price": round(o.price_open, 5),
                "time_setup": str(o.time_setup),
                "state": str(o.state),
            })
        return {"orders": out}

    def exposed_login(self, login: int, password: str, server: str, timeout: int = 60000) -> dict:
        if not _ensure_mt5(login=login, password=password, server=server):
            return {"error": "MT5 not initialized"}
        result = mt5.login(login, password=password, server=server, timeout=timeout)
        if result:
            global _mt5_initialized
            _mt5_initialized = True
            return {"status": "logged_in", "login": login, "server": server}
        return {"error": f"MT5 login failed: {mt5.last_error()}"}

    def exposed_terminal_info(self) -> dict:
        if not _ensure_mt5():
            return {"error": "MT5 not initialized"}
        info = mt5.terminal_info()
        if info is None:
            return {"error": "Cannot get terminal info"}
        return {
            "connected": info.connected,
            "trade_allowed": info.trade_allowed,
            "build": info.build,
            "path": info.path,
        }

    def exposed_raw_call(self, method: str, *args, **kwargs) -> dict:
        if not _ensure_mt5():
            return {"error": "MT5 not initialized"}
        if not hasattr(mt5, method):
            return {"error": f"mt5.{method} does not exist"}
        try:
            result = getattr(mt5, method)(*args, **kwargs)
            if hasattr(result, "_asdict"):
                return {"result": result._asdict()}
            elif hasattr(result, "__dict__"):
                return {"result": result.__dict__}
            else:
                return {"result": result}
        except Exception as e:
            return {"error": str(e)}


def main():
    host = "0.0.0.0"
    port = 18812
    logger.info("Starting MT5Service on %s:%d", host, port)
    try:
        t = ThreadedServer(
            MT5Service,
            hostname=host,
            port=port,
            reuse_addr=True,
            protocol_config={"allow_public_attrs": True},
        )
        logger.info("MT5Service ready")
        t.start()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        sys.exit(0)
    except Exception as e:
        logger.error("Failed to start: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
