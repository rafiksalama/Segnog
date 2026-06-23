## ---------------------------------------------------------------------------
##  Segnog — All-in-one container
##  Bundles DragonflyDB + FalkorDB + Memory Service + UI in a single image.
## ---------------------------------------------------------------------------

# ── Build Python deps ──────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Install all other dependencies (cached unless pyproject.toml changes)
COPY pyproject.toml ./
RUN mkdir -p src/memory_service client && \
    touch src/memory_service/__init__.py && \
    pip install --no-cache-dir --prefix=/install --no-deps . && \
    pip install --no-cache-dir --prefix=/install . && \
    rm -rf src/ client/

# Bake local-embedding deps into the image (CPU torch + sentence-transformers).
# Previously these were pip-installed at container start into an ephemeral
# /pip-install, which crash-looped on Azure when the 2-3 min boot-time install
# was cut short by the startup probe (or skipped via a stale sentinel). Baking
# them makes startup fast, deterministic, and free of any network dependency.
RUN pip install --no-cache-dir --prefix=/install \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    torch "sentence-transformers>=3.0.0"

# Copy actual source and reinstall (fast — only our package, deps are cached)
COPY src/ src/
COPY client/ client/
RUN pip install --no-cache-dir --prefix=/install --no-deps .

# ── Build UI ───────────────────────────────────────────────────────────────
FROM node:20-slim AS ui-builder

WORKDIR /ui

COPY ui/package.json ui/package-lock.json ./
RUN npm ci

COPY ui/ .
RUN npm run build

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

# ── Install NATS server (arch-aware: amd64 + arm64) ─────────────────────
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
      amd64) NATS_ARCH=amd64 ;; \
      arm64) NATS_ARCH=arm64 ;; \
      *) echo "Unsupported arch: $ARCH" && exit 1 ;; \
    esac && \
    curl -L "https://github.com/nats-io/nats-server/releases/download/v2.10.24/nats-server-v2.10.24-linux-${NATS_ARCH}.tar.gz" | \
    tar xz -C /usr/local/bin --strip-components=1 "nats-server-v2.10.24-linux-${NATS_ARCH}/nats-server" && \
    apt-get purge -y curl && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# ── Copy Python packages + app source ────────────────────────────────────
COPY --from=builder /install /usr/local
COPY src/ src/
COPY client/ client/
COPY settings.toml ./

# ── Copy built UI ─────────────────────────────────────────────────────────
COPY --from=ui-builder /ui/dist /app/ui/dist

# ── Entrypoint + eventlistener stub ───────────────────────────────────────
COPY entrypoint.sh /app/entrypoint.sh
COPY sync-data.sh /app/sync-data.sh
RUN chmod +x /app/entrypoint.sh /app/sync-data.sh

# ── Data directories + pip-install volume mount point ──────────────────────
RUN mkdir -p /data/dragonfly /data/falkordb /data/nats /var/log/supervisor /pip-install
ENV PYTHONPATH="/pip-install"

# ── Supervisord config ────────────────────────────────────────────────────
# Kept as a real file (not a BuildKit heredoc) so both local BuildKit and the
# ACR Tasks build engine can build this image.
COPY supervisor-segnog.conf /etc/supervisor/conf.d/segnog.conf

# gRPC + REST (port 9000 also serves the UI at http://localhost:9000/)
EXPOSE 50051 9000

# Persist database state via Azure Files (mounted at /backup/*)
VOLUME ["/backup/dragonfly", "/backup/falkordb", "/backup/nats", "/pip-install"]

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/health')" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
