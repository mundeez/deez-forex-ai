# =============================================================================
# deez-forex-ai MT5 Container
# Based on gmag11/metatrader5_vnc (proven Wine + MT5 setup)
# Strips VNC, keeps headless Wine/MT5 + ZMQ bridge
# =============================================================================

FROM gmag11/metatrader5_vnc:latest

USER root

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV WINEPREFIX=/config/.wine
ENV WINEDEBUG=-all
ENV DISPLAY=:99

# Install additional dependencies for ZMQ bridge
# Allow unsigned repos (WineHQ key may be missing in base image)
RUN apt-get update --allow-insecure-repositories || true && \
    apt-get install -y --no-install-recommends --allow-unauthenticated \
    wget \
    curl \
    netcat-openbsd \
    supervisor \
    xvfb \
    xauth \
    && rm -rf /var/lib/apt/lists/*

# Ensure pyzmq is installed in Linux Python
RUN pip3 install --break-system-packages --no-cache-dir pyzmq

# Create supervisor run directory
RUN mkdir -p /var/run/supervisor

# Create app directory
WORKDIR /app

# Copy supervisord config and scripts
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY startup.sh /app/startup.sh
COPY run_mt5.sh /app/run_mt5.sh
COPY run_rpyc.sh /app/run_rpyc.sh
COPY health_check.py /app/health_check.py
COPY rpyc_server.py /app/rpyc_server.py
COPY zmq_bridge.py /app/zmq_bridge.py
RUN chmod +x /app/startup.sh /app/run_mt5.sh /app/run_rpyc.sh

# Expose ZMQ ports (internal Docker network only)
EXPOSE 5555 5556

# Health check via Python script
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python3 /app/health_check.py || exit 1

# Entrypoint
ENTRYPOINT ["/app/startup.sh"]
