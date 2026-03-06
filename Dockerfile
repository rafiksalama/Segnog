## ---------------------------------------------------------------------------
##  Segnog — All-in-one container
##  Bundles DragonflyDB + FalkorDB + Memory Service in a single image.
## ---------------------------------------------------------------------------

# ── Build Python deps ──────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ src/
COPY client/ client/

RUN pip install --no-cache-dir --prefix=/install .

# ── Runtime ────────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# supervisord + runtime libs needed by FalkorDB (libgomp, libssl, libstdc++)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        supervisor libgomp1 libssl3 libstdc++6 && \
    rm -rf /var/lib/apt/lists/*

# ── Install DragonflyDB binary from official image ───────────────────────
COPY --from=docker.dragonflydb.io/dragonflydb/dragonfly:latest /usr/local/bin/dragonfly /usr/local/bin/dragonfly

# ── Install FalkorDB (Redis server + graph module) from official image ────
COPY --from=falkordb/falkordb:latest /usr/local/bin/redis-server /usr/local/bin/falkordb-server
COPY --from=falkordb/falkordb:latest /var/lib/falkordb/bin/falkordb.so /opt/falkordb/falkordb.so

# ── Copy Python packages + app source ────────────────────────────────────
COPY --from=builder /install /usr/local
COPY src/ src/
COPY client/ client/
COPY settings.toml ./

# ── Data directories ──────────────────────────────────────────────────────
RUN mkdir -p /data/dragonfly /data/falkordb /var/log/supervisor

# ── Supervisord config ────────────────────────────────────────────────────
COPY <<'EOF' /etc/supervisor/conf.d/segnog.conf
[supervisord]
nodaemon=true
logfile=/var/log/supervisor/supervisord.log
pidfile=/var/run/supervisord.pid

[program:dragonfly]
command=dragonfly --port 6381 --dir /data/dragonfly --dbfilename dump
autostart=true
autorestart=true
stdout_logfile=/var/log/supervisor/dragonfly.log
stderr_logfile=/var/log/supervisor/dragonfly.log

[program:falkordb]
command=falkordb-server --port 6380 --dir /data/falkordb --loadmodule /opt/falkordb/falkordb.so
autostart=true
autorestart=true
stdout_logfile=/var/log/supervisor/falkordb.log
stderr_logfile=/var/log/supervisor/falkordb.log

[program:memory-service]
command=memory-service
directory=/app
autostart=true
autorestart=true
startsecs=5
startretries=3
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
environment=MEMORY_SERVICE_DRAGONFLY__URL="redis://localhost:6381",MEMORY_SERVICE_FALKORDB__URL="redis://localhost:6380"
EOF

# gRPC + REST
EXPOSE 50051 9000

# Persist database state
VOLUME ["/data/dragonfly", "/data/falkordb"]

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/health')" || exit 1

ENTRYPOINT ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/segnog.conf"]
