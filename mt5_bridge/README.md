# MT5 Desktop ZeroMQ Bridge

Direct connection from `deez-forex-ai` backend to your local MetaTrader 5 terminal via ZeroMQ. No cloud dependency.

## Prerequisites

- MetaTrader 5 (MacBook Pro via Wine/PlayOnMac, or native Windows)
- [ZmqSocket MQL5 library](https://github.com/dingmaotu/mql-zmq) installed in MT5's `Include/` folder
- `pyzmq` installed in backend (already added to `requirements.txt`)

## How It Works

```
Your MacBook (MT5)  <--SSH tunnel-->  Linux Server (Docker backend)
     :5555  REP socket                    MT5ZMQClient
     :5556  PUB socket                    MT5ZMQSubscriber
```

## Step 1: Install the ZmqSocket Library in MT5

1. Download the [mql-zmq](https://github.com/dingmaotu/mql-zmq) release.
2. Copy `ZmqSocket.mqh` and the DLLs into your MT5 data folder:
   - `MQL5/Include/ZmqSocket.mqh`
   - `MQL5/Libraries/libsodium.dll`
   - `MQL5/Libraries/libzmq.dll`

## Step 2: Compile and Attach the EA

1. Open `mt5_bridge/ZeroMQ_Server.mq5` in MetaEditor.
2. Compile (F7).
3. Attach the EA to any chart in MT5.
4. In the EA inputs:
   - `ZMQ_HOST`: `0.0.0.0` (binds to all interfaces)
   - `ZMQ_REQ_PORT`: `5555`
   - `ZMQ_PUB_PORT`: `5556`
   - `DEMO_ONLY_GUARD`: `true` (recommended for testing)

> **Important:** Enable `Allow Algo Trading` and `Allow WebRequest` in MT5 options.

## Step 3: Create the SSH Reverse Tunnel

On your **MacBook Pro** (where MT5 runs), open Terminal and run:

```bash
ssh -R 5555:localhost:5555 -R 5556:localhost:5556 user@your-linux-server-ip
```

This forwards ports `5555` and `5556` from the Linux server back to your Mac's MT5.

> **Linux Docker users:** `host.docker.internal` does not auto-resolve on Linux. Add `--add-host=host.docker.internal:host-gateway` to your backend container or set `MT5_ZMQ_HOST` to the host's LAN IP.

## Step 4: Configure Environment Variables

In your backend `.env`:

```env
DATA_PROVIDER=mt5_zmq
MT5_ZMQ_HOST=host.docker.internal
MT5_ZMQ_REQ_PORT=5555
MT5_ZMQ_PUB_PORT=5556
```

Restart the backend:

```bash
docker-compose restart backend
```

## Step 5: Test

1. Check the backend logs for successful ZMQ subscriber startup.
2. Open the frontend dashboard. Prices should now stream from your desktop MT5.
3. Place a paper trade via the Manual Trade panel (select "MT5 Desktop (ZMQ)" broker).
4. Confirm the trade appears in your MT5 terminal.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `MT5 ZMQ timeout` | Ensure the SSH tunnel is active and MT5 EA is running. |
| `No price data` | Check that `Subscribe` topics include `"prices"` in the WebSocket. |
| `DEMO_ONLY_GUARD active` | The EA blocks live trades on non-demo accounts. Set `DEMO_ONLY_GUARD=false` only when ready. |
| Docker can't reach host | Use `extra_hosts: ["host.docker.internal:host-gateway"]` in `docker-compose.yml`. |

## Commands Reference

| Action | Description |
|--------|-------------|
| `GET_PRICE` | Bid/ask for a symbol |
| `GET_CANDLES` | OHLCV history |
| `GET_ACCOUNT` | Balance, equity, margin |
| `GET_POSITIONS` | List of open positions |
| `TRADE` | Place market order |
| `CLOSE` | Close position by ticket |
