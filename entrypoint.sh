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

if [ "$NEED_LOCAL" = true ]; then
    # Gate on actual importability, not just the sentinel. A stale .installed
    # sentinel left by an interrupted/partial install (or a wiped ephemeral
    # /pip-install) would otherwise make us skip while the package is missing,
    # crash-looping memory-service. Importability is the source of truth.
    if python -c "import sentence_transformers" >/dev/null 2>&1; then
        echo "[entrypoint] sentence-transformers already importable, skipping install."
    else
        echo "[entrypoint] Local embedding backend detected, sentence-transformers missing."
        echo "[entrypoint] Installing torch (CPU) + sentence-transformers (2-3 min on first run)..."
        pip install --no-cache-dir --target /pip-install \
            --extra-index-url https://download.pytorch.org/whl/cpu \
            torch "sentence-transformers>=3.0.0"
        touch "$SENTINEL"
        # Verify the install actually took before handing off to supervisord.
        if ! python -c "import sentence_transformers" >/dev/null 2>&1; then
            echo "[entrypoint] FATAL: sentence-transformers still not importable after install." >&2
            exit 1
        fi
        echo "[entrypoint] Local embedding dependencies installed and verified."
    fi
else
    echo "[entrypoint] Embedding backend is remote — skipping local deps install."
fi

echo "[entrypoint] Starting supervisord..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/segnog.conf
