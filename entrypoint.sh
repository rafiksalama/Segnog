#!/usr/bin/env bash
set -euo pipefail

# ── Self-healing: install local embedding deps if needed ─────────────────────
SETTINGS="/app/settings.toml"
SENTINEL="/pip-install/.installed"
NEED_LOCAL=false

# Check if local embeddings configured (grep settings.toml + env var override)
if [ -f "$SETTINGS" ] && grep -q 'backend[[:space:]]*=[[:space:]]*"local"' "$SETTINGS" 2>/dev/null; then
    NEED_LOCAL=true
fi
if [ "${MEMORY_SERVICE_EMBEDDINGS__BACKEND:-}" = "local" ]; then
    NEED_LOCAL=true
fi

# Ensure /pip-install is always on PYTHONPATH (needed for local embeds)
export PYTHONPATH="/pip-install:${PYTHONPATH:-}"

if [ "$NEED_LOCAL" = true ] && [ ! -f "$SENTINEL" ]; then
    echo "[entrypoint] Local embedding backend detected. Installing torch (CPU) + sentence-transformers..."
    echo "[entrypoint] This may take 2-3 minutes on first run."
    pip install --no-cache-dir --target /pip-install \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        torch "sentence-transformers>=3.0.0"
    touch "$SENTINEL"
    echo "[entrypoint] Local embedding dependencies installed."
elif [ "$NEED_LOCAL" = true ]; then
    echo "[entrypoint] Local embedding dependencies already installed, skipping."
else
    echo "[entrypoint] Embedding backend is remote — skipping local deps install."
fi

echo "[entrypoint] Starting supervisord..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/segnog.conf
