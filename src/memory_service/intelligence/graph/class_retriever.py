"""
Embedding-based Schema.org class retriever.

Embeds the source text at inference time, computes cosine similarity
against pre-embedded Schema.org class descriptions, and returns the
top-K most relevant classes as a formatted string for prompt injection.

Supports two embedding backends:
  - "remote" (default): OpenAI-compatible API via AsyncOpenAI
  - "local": sentence-transformers (CPU)

Class embeddings are computed once (lazily), persisted to a JSON cache
file alongside the schema JSON-LD, and cached in-process. An asyncio
lock prevents duplicate work when multiple coroutines start up concurrently.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Callable, Awaitable

import numpy as np

if TYPE_CHECKING:
    from ...ontology.schema_org import SchemaOrgOntology

logger = logging.getLogger(__name__)

# Global lock to prevent concurrent embed_classes() initialisation
_embed_classes_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _embed_classes_lock
    if _embed_classes_lock is None:
        _embed_classes_lock = asyncio.Lock()
    return _embed_classes_lock


def _get_embed_fn() -> Callable[[str], Awaitable[list[float]]]:
    """Return the appropriate async embed function based on config."""
    from ...config import get_embedding_backend, get_embedding_model

    backend = get_embedding_backend()
    model = get_embedding_model()

    if backend == "local":
        from ...storage.long_term.embed import aembed_single

        async def _local_embed(text: str) -> list[float]:
            return await aembed_single(text, model_name=model)

        return _local_embed
    else:
        from openai import AsyncOpenAI
        from ...config import get_embedding_api_key, get_embedding_base_url

        _EMBED_CONCURRENCY = 5
        _embed_semaphore: asyncio.Semaphore | None = None

        def _get_semaphore() -> asyncio.Semaphore:
            nonlocal _embed_semaphore
            if _embed_semaphore is None:
                _embed_semaphore = asyncio.Semaphore(_EMBED_CONCURRENCY)
            return _embed_semaphore

        client = AsyncOpenAI(
            api_key=get_embedding_api_key(),
            base_url=get_embedding_base_url(),
        )

        async def _remote_embed(text: str) -> list[float]:
            async with _get_semaphore():
                resp = await client.embeddings.create(
                    model=model,
                    input=text,
                    encoding_format="float",
                )
            return resp.data[0].embedding

        return _remote_embed


async def retrieve_relevant_classes(
    source_text: str,
    onto: SchemaOrgOntology,
    top_k: int = 60,
) -> str:
    """
    Embed source_text and return the top-K most semantically similar
    Schema.org class descriptions as a formatted string.

    Class embeddings are loaded from a disk cache if available; otherwise
    computed once and saved. An asyncio lock prevents duplicate work.

    Args:
        source_text: The episode/conversation text being processed.
        onto: The shared SchemaOrgOntology singleton.
        top_k: Number of classes to return (default 60).

    Returns:
        Multi-line string of the form:
          ClassName(ParentClass) — description
          ...
    """
    embed_fn = _get_embed_fn()

    # Build/fetch cached class embeddings (lock prevents duplicate concurrent build)
    async with _get_lock():
        class_embs = await onto.embed_classes(embed_fn)

    if not class_embs:
        logger.warning(
            "No class embeddings available — entity extraction will use no relevant classes"
        )
        return ""

    # Embed the source text
    text_vec = np.array(await embed_fn(source_text), dtype=np.float32)
    norm = np.linalg.norm(text_vec)
    if norm > 0:
        text_vec /= norm

    # Compute cosine similarity against all indexed classes
    scores: dict[str, float] = {}
    for cls_name, emb in class_embs.items():
        v = np.array(emb, dtype=np.float32)
        v_norm = np.linalg.norm(v)
        if v_norm > 0:
            scores[cls_name] = float(np.dot(text_vec, v / v_norm))

    # Select top-K by score
    top_classes = sorted(scores, key=scores.__getitem__, reverse=True)[:top_k]

    lines = []
    for cls_name in top_classes:
        info = onto._classes[cls_name]
        parent_str = f"({','.join(info.parents)})" if info.parents else ""
        comment_str = f" — {info.comment}" if info.comment else ""
        lines.append(f"  {cls_name}{parent_str}{comment_str}")

    logger.debug("Retrieved %d relevant Schema.org classes for extraction", len(lines))
    return "\n".join(lines)
