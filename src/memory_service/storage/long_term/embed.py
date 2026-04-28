"""
Local embedding backend using sentence-transformers.

Provides a process-level singleton that wraps SentenceTransformer for
sync-in-async usage. All BaseStore and class_retriever calls delegate
to this module when embeddings.backend = "local".
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import List

logger = logging.getLogger(__name__)

_model = None
_lock = threading.Lock()


def get_local_embedder(model_name: str = "all-MiniLM-L6-v2"):
    """Load SentenceTransformer once (thread-safe). Returns the model."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError:
                    raise ImportError(
                        "sentence-transformers is not installed. "
                        "Install it with: pip install 'agent-memory-service[local-embed]' "
                        "or run the setup wizard with local embedding enabled."
                    )
                logger.info("Loading local embedding model: %s", model_name)
                _model = SentenceTransformer(model_name)
                logger.info(
                    "Local embedding model loaded: %s (dim=%d)",
                    model_name,
                    _model.get_embedding_dimension(),
                )
    return _model


def embed_single(text: str, model_name: str = "all-MiniLM-L6-v2") -> List[float]:
    """Synchronous single-text embedding. Returns list[float]."""
    m = get_local_embedder(model_name)
    vec = m.encode_document([text])
    return vec[0].tolist()


def embed_batch(
    texts: List[str], model_name: str = "all-MiniLM-L6-v2"
) -> List[List[float]]:
    """Synchronous batch embedding. Returns list[list[float]]."""
    if not texts:
        return []
    m = get_local_embedder(model_name)
    vecs = m.encode_document(texts)
    return [v.tolist() for v in vecs]


async def aembed_single(
    text: str, model_name: str = "all-MiniLM-L6-v2"
) -> List[float]:
    """Async wrapper for single embedding (runs in thread pool)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, embed_single, text, model_name)


async def aembed_batch(
    texts: List[str], model_name: str = "all-MiniLM-L6-v2"
) -> List[List[float]]:
    """Async wrapper for batch embedding (runs in thread pool)."""
    if not texts:
        return []
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, embed_batch, texts, model_name)
