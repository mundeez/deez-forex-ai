# MT5 Docker Container

Wine-based MetaTrader 5 container with ZeroMQ bridge for `deez-forex-ai`.

## Architecture

```
+------------------+     +------------------+     +------------------+
|   Backend API    |<--->|  ZMQ Bridge      |<--->|  MT5 Terminal    |
|  (Python/FastAPI)|     |  (Wine Python)   |     |  (Wine/Windows)  |
+------------------+     +------------------+     +------------------+
       |                         |
       |    REQ/REP :5555        |
       |    PUB/SUB :5556        |
       v                         v
  Docker Network            Docker Network
```

## Ports

| Port | Protocol | Purpose |
|------|----------|---------|
| 5555 | ZMQ REQ/REP | Commands (GET_PRICE, GET_CANDLES, TRADE, etc.) |
| 5556 | ZMQ PUB/SUB | Real-time tick streaming |
| 18812 | RPyC | Internal MT5 API access (debugging) |

## Environment Variables

Set in backend `.env`:

```env
DATA_PROVIDER=mt5_zmq
MT5_ZMQ_HOST=mt5          # Docker service name
MT5_ZMQ_REQ_PORT=5555
MT5_ZMQ_PUB_PORT=5556
```

## Build & Run

```bash
# Standalone
docker build -t deez-forex-mt5 -f mt5/Dockerfile mt5/
docker run -d --name mt5 --privileged -p 15555:5555 -p 15556:5556 -v mt5_config:/config deez-forex-mt5

# Docker Compose (full stack)
docker-compose up -d mt5
```

## First Run

The container downloads and installs at runtime:
1. Wine Mono (for .NET support)
2. MetaTrader 5 terminal
3. Python 3.9 in Wine
4. MetaTrader5 Python package + pyzmq

This takes ~3-5 minutes on first start. The `/config` volume persists everything.

## Health Check

```bash
docker exec deez-forex-mt5 python3 /app/health_check.py
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `MT5 not initialized` | Add a broker account via the frontend settings page |
| ZMQ timeout | Check that the container is healthy and ports are mapped |
| `wine: socket : Function not implemented` | Ensure `--privileged` flag is set |
