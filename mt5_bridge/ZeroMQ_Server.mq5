//+------------------------------------------------------------------+
//|                                            ZeroMQ_Server.mq5     |
//|  Direct MT5 bridge for deez-forex-ai via ZeroMQ                  |
//|  Uses direct libzmq.dll imports (no wrapper classes)             |
//+------------------------------------------------------------------+
#property copyright "deez-forex-ai"
#property version   "1.02"
#property strict

#include <Trade/Trade.mqh>

//--- ZeroMQ constants
#define ZMQ_PUB 1
#define ZMQ_REP 4
#define ZMQ_DONTWAIT 1
#define ZMQ_RCVTIMEO 27

//--- Direct libzmq.dll imports
#import "libzmq.dll"
   long  zmq_ctx_new();
   long  zmq_socket(long context, int type);
   int   zmq_bind(long socket, string addr);
   int   zmq_send(long socket, uchar &buf[], int len, int flags);
   int   zmq_recv(long socket, uchar &buf[], int len, int flags);
   int   zmq_setsockopt(long socket, int option, int &optval[], int optvallen);
   int   zmq_setsockopt(long socket, int option, int optval, int optvallen);
   int   zmq_close(long socket);
   int   zmq_ctx_term(long context);
   int   zmq_errno();
#import

//--- Input parameters
input string ZMQ_HOST        = "0.0.0.0";
input int    ZMQ_REQ_PORT    = 5555;      // Command/Response port
input int    ZMQ_PUB_PORT    = 5556;      // Tick publisher port
input int    TIMER_MS        = 100;       // Command poll interval
input bool   DEMO_ONLY_GUARD = true;      // Block live trades on non-demo accounts
input int    MAGIC_NUMBER    = 123456;    // Expert magic number (make unique per instance)
input int    MAX_MSG_SIZE    = 65536;     // Max ZMQ message size (was 4096)

//--- Sockets
long g_context   = 0;
long g_rep_sock  = 0;
long g_pub_sock  = 0;

//--- Trade helper
CTrade g_trade;

//+------------------------------------------------------------------+
int OnInit()
{
   g_trade.SetExpertMagicNumber(MAGIC_NUMBER);
   g_trade.SetDeviationInPoints(10);

   g_context = zmq_ctx_new();
   if(g_context == 0)
   {
      Print("zmq_ctx_new failed");
      return INIT_FAILED;
   }

   g_rep_sock = zmq_socket(g_context, ZMQ_REP);
   g_pub_sock = zmq_socket(g_context, ZMQ_PUB);

   if(g_rep_sock == 0 || g_pub_sock == 0)
   {
      Print("zmq_socket failed");
      return INIT_FAILED;
   }

   // Set 100ms receive timeout on REP socket
   int timeout = 100;
   zmq_setsockopt(g_rep_sock, ZMQ_RCVTIMEO, timeout, 4);

   string rep_addr = StringFormat("tcp://%s:%d", ZMQ_HOST, ZMQ_REQ_PORT);
   string pub_addr = StringFormat("tcp://%s:%d", ZMQ_HOST, ZMQ_PUB_PORT);

   if(zmq_bind(g_rep_sock, rep_addr) != 0)
   {
      Print("REP bind failed on ", rep_addr, " errno:", zmq_errno());
      return INIT_FAILED;
   }
   Print("ZeroMQ REP bound to ", rep_addr);

   if(zmq_bind(g_pub_sock, pub_addr) != 0)
   {
      Print("PUB bind failed on ", pub_addr, " errno:", zmq_errno());
      return INIT_FAILED;
   }
   Print("ZeroMQ PUB bound to ", pub_addr);

   EventSetMillisecondTimer(TIMER_MS);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   if(g_rep_sock != 0) zmq_close(g_rep_sock);
   if(g_pub_sock != 0) zmq_close(g_pub_sock);
   if(g_context != 0)  zmq_ctx_term(g_context);
   Print("ZeroMQ Server stopped.");
}

//+------------------------------------------------------------------+
void OnTick()
{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick)) return;

   string json = StringFormat(
      "{\"type\":\"tick\",\"symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f,\"last\":%.5f,\"volume\":%I64u,\"timestamp\":%I64d}",
      _Symbol, tick.bid, tick.ask, tick.last, tick.volume, tick.time_msc
   );

   SendString(g_pub_sock, json);
}

//+------------------------------------------------------------------+
void OnTimer()
{
   // Poll REP socket for commands (non-blocking due to RCVTIMEO)
   string payload;
   while(RecvString(g_rep_sock, payload))
   {
      string response = HandleCommand(payload);
      SendString(g_rep_sock, response);
   }
}

//+------------------------------------------------------------------+
void SendString(long sock, string msg)
{
   uchar buf[];
   StringToCharArray(msg, buf, 0, StringLen(msg), CP_UTF8);
   int len = ArraySize(buf);
   zmq_send(sock, buf, len, 0);
}

//+------------------------------------------------------------------+
bool RecvString(long sock, string &out)
{
   uchar buf[];
   ArrayResize(buf, MAX_MSG_SIZE);
   int rc = zmq_recv(sock, buf, MAX_MSG_SIZE, 0);
   if(rc <= 0) return false;
   out = CharArrayToString(buf, 0, rc, CP_UTF8);
   return true;
}

//+------------------------------------------------------------------+
string HandleCommand(string json)
{
   string action = ExtractStringField(json, "action");
   string symbol = ExtractStringField(json, "symbol");
   if(symbol == "") symbol = _Symbol;

   // Validate symbol exists
   if(!SymbolSelect(symbol, true))
      return "{\"error\":\"Invalid symbol: " + symbol + "\"}";

   Print("[ZMQ] Command: ", action, " Symbol: ", symbol);

   if(action == "GET_PRICE")
      return HandleGetPrice(symbol);
   if(action == "GET_CANDLES")
      return HandleGetCandles(json, symbol);
   if(action == "GET_ACCOUNT")
      return HandleGetAccount();
   if(action == "GET_POSITIONS")
      return HandleGetPositions();
   if(action == "TRADE")
      return HandleTrade(json);
   if(action == "CLOSE")
      return HandleClose(json);

   Print("[ZMQ] Unknown action: ", action);
   return "{\"error\":\"Unknown action: " + action + "\"}";
}

//+------------------------------------------------------------------+
string HandleGetPrice(string symbol)
{
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
      return "{\"error\":\"Unable to get price for " + symbol + "\"}";

   return StringFormat(
      "{\"symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f,\"timestamp\":%I64d}",
      symbol, tick.bid, tick.ask, tick.time_msc
   );
}

//+------------------------------------------------------------------+
string HandleGetCandles(string json, string symbol)
{
   string tf_str = ExtractStringField(json, "timeframe");
   int limit     = ExtractIntField(json, "limit");
   if(limit <= 0) limit = 500;
   if(limit > 2000) limit = 2000;

   ENUM_TIMEFRAMES tf = StringToTimeframe(tf_str);

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(symbol, tf, 0, limit, rates);
   if(copied <= 0)
      return "{\"error\":\"No candle data available\"}";

   string result = "{\"candles\":[\n";
   for(int i = 0; i < copied; i++)
   {
      if(i > 0) result += ",\n";
      result += StringFormat(
         "{\"timestamp\":%I64d,\"open\":%.5f,\"high\":%.5f,\"low\":%.5f,\"close\":%.5f,\"volume\":%d}",
         rates[i].time * 1000, rates[i].open, rates[i].high, rates[i].low, rates[i].close, (int)rates[i].tick_volume
      );
   }
   result += "\n]}";
   return result;
}

//+------------------------------------------------------------------+
string HandleGetAccount()
{
   return StringFormat(
      "{\"balance\":%.2f,\"equity\":%.2f,\"margin\":%.2f,\"free_margin\":%.2f,\"currency\":\"%s\",\"leverage\":%d}",
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_MARGIN),
      AccountInfoDouble(ACCOUNT_MARGIN_FREE),
      AccountInfoString(ACCOUNT_CURRENCY),
      (int)AccountInfoInteger(ACCOUNT_LEVERAGE)
   );
}

//+------------------------------------------------------------------+
string HandleGetPositions()
{
   int total = PositionsTotal();
   string result = "{\"positions\":[\n";
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(i > 0) result += ",\n";
      result += StringFormat(
         "{\"ticket\":%I64u,\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.2f,\"open_price\":%.5f,\"sl\":%.5f,\"tp\":%.5f,\"profit\":%.2f}",
         ticket,
         PositionGetString(POSITION_SYMBOL),
         PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? "BUY" : "SELL",
         PositionGetDouble(POSITION_VOLUME),
         PositionGetDouble(POSITION_PRICE_OPEN),
         PositionGetDouble(POSITION_SL),
         PositionGetDouble(POSITION_TP),
         PositionGetDouble(POSITION_PROFIT)
      );
   }
   result += "\n]}";
   return result;
}

//+------------------------------------------------------------------+
string HandleTrade(string json)
{
   if(DEMO_ONLY_GUARD && AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO)
      return "{\"error\":\"DEMO_ONLY_GUARD active — live trading blocked\"}";

   string actionType = ExtractStringField(json, "actionType");
   string symbol     = ExtractStringField(json, "symbol");
   double volume     = ExtractDoubleField(json, "volume");
   double sl         = ExtractDoubleField(json, "stopLoss");
   double tp         = ExtractDoubleField(json, "takeProfit");
   if(symbol == "") symbol = _Symbol;

   ENUM_ORDER_TYPE order_type = (actionType == "ORDER_TYPE_BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;

   MqlTradeRequest request = {};
   request.action       = TRADE_ACTION_DEAL;
   request.symbol       = symbol;
   request.volume       = volume;
   request.type         = order_type;
   request.deviation    = 10;
   request.magic        = 123456;
   request.comment      = "deez-forex-ai";
   if(sl > 0) request.sl = sl;
   if(tp > 0) request.tp = tp;

   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
      return "{\"error\":\"Cannot get price\"}";
   request.price = (order_type == ORDER_TYPE_BUY) ? tick.ask : tick.bid;

   MqlTradeResult result = {};
   if(!OrderSend(request, result))
      return StringFormat("{\"error\":\"OrderSend failed: %d\",\"result\":\"failed\"}", GetLastError());

   return StringFormat(
      "{\"ticket\":%I64u,\"volume\":%.2f,\"price\":%.5f,\"result\":\"done\"}",
      result.order, result.volume, result.price
   );
}

//+------------------------------------------------------------------+
string HandleClose(string json)
{
   if(DEMO_ONLY_GUARD && AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO)
      return "{\"error\":\"DEMO_ONLY_GUARD active — live trading blocked\"}";

   string ticket_str = ExtractStringField(json, "ticket");
   ulong ticket = StringToInteger(ticket_str);
   if(ticket == 0)
      return "{\"error\":\"Invalid ticket\"}";

   if(!g_trade.PositionClose(ticket))
      return StringFormat("{\"error\":\"PositionClose failed: %d\",\"result\":\"failed\"}", GetLastError());

   return "{\"ticket\":\"" + ticket_str + "\",\"result\":\"done\"}";
}

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
string ExtractStringField(string json, string key)
{
   string pattern = "\"" + key + "\":\"";
   int start = StringFind(json, pattern);
   if(start == -1)
   {
      pattern = "\"" + key + "\":";
      start = StringFind(json, pattern);
      if(start == -1) return "";
      start += StringLen(pattern);
      int end = StringFind(json, ",", start);
      if(end == -1) end = StringFind(json, "}", start);
      return StringSubstr(json, start, end - start);
   }
   start += StringLen(pattern);
   int end = StringFind(json, "\"", start);
   return StringSubstr(json, start, end - start);
}

//+------------------------------------------------------------------+
int ExtractIntField(string json, string key)
{
   string val = ExtractStringField(json, key);
   return (int)StringToInteger(val);
}

//+------------------------------------------------------------------+
double ExtractDoubleField(string json, string key)
{
   string val = ExtractStringField(json, key);
   return StringToDouble(val);
}

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES StringToTimeframe(string tf)
{
   if(tf == "1m")  return PERIOD_M1;
   if(tf == "5m")  return PERIOD_M5;
   if(tf == "15m") return PERIOD_M15;
   if(tf == "30m") return PERIOD_M30;
   if(tf == "1h")  return PERIOD_H1;
   if(tf == "4h")  return PERIOD_H4;
   if(tf == "1d")  return PERIOD_D1;
   if(tf == "1w")  return PERIOD_W1;
   return PERIOD_H1;
}
//+------------------------------------------------------------------+
