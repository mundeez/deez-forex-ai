# MT5 VNC Setup Instructions

## Current Status

The MT5 Docker container is running with:
- **VNC Access**: http://localhost:16901 (KasmVNC web interface)
- **MT5 Login**: Already completed with demo account 5051688110 (MetaQuotes-Demo)
- **ZeroMQ EA**: Compiled and ready at `MQL5/Experts/deez-forex-ai/ZeroMQ_Server.ex5`
- **ZeroMQ Script**: Compiled and ready at `MQL5/Scripts/ZeroMQ_Script.ex5`
- **Backend ZMQ Config**: Points to `mt5:5555` (REQ) and `mt5:5556` (PUB)

## One-Time Setup Required

The ZeroMQ EA needs to be attached to a chart for the backend to communicate with MT5.

### Option A: Attach the Expert Advisor (Recommended for persistence)

1. Open VNC: http://localhost:16901
2. In MT5, press **Ctrl+N** to open the **Navigator** panel
3. Click the **Expert Advisors** tab (3rd tab)
4. Expand the **deez-forex-ai** folder
5. Find **ZeroMQ_Server** and **double-click** it
6. A settings dialog will appear. Click **OK** to accept defaults:
   - ZMQ_HOST: `0.0.0.0`
   - ZMQ_REQ_PORT: `5555`
   - ZMQ_PUB_PORT: `5556`
7. The EA is now attached to the EURUSD chart
8. **Save the profile**: File > Profiles > Save As > name it "default_zmq"
9. Set as default: File > Profiles > default_zmq (checkmark)

### Option B: Run the Script (Quick test)

1. Open VNC: http://localhost:16901
2. In MT5, press **Ctrl+N** to open the **Navigator** panel
3. Click the **Scripts** tab (4th tab)
4. Find **ZeroMQ_Script** and **double-click** it
5. The script will start and bind to ports 5555/5556
6. Note: Scripts stop when you close MT5 (unlike EAs which persist on charts)

## Verify ZMQ is Working

After attaching the EA, verify with:

```bash
curl http://localhost:28000/api/v1/mt5/status
```

You should see:
- `mt5_terminal_running: true`
- `zmq_bridge_running: true`
- `mt5_initialized: true`

## Nginx Proxy

An nginx reverse proxy is running on port 28080, proxying to the VNC.
To access via your domain, configure DNS for `fx.deeztechnology.solutions` 
to point to this server's IP, then update nginx config with SSL certs.

## Architecture

```
Backend (port 28000)  <--ZMQ-->  MT5 MQL5 EA (port 5555/5556 inside container)
                                      |
                                   [Wine]
                                      |
                                MT5 Terminal
                                      |
                                  KasmVNC
                                      |
User <--Browser--> Nginx (port 28080) --proxy--> KasmVNC (port 6901 inside container)
```
