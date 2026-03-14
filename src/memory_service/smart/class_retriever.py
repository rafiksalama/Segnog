"""
Embedding-based Schema.org class retriever.

Embeds the source text at inference time, computes cosine similarity
against pre-embedded Schema.org class descriptions, and returns the
top-K most relevant classes as a formatted string for prompt injection.

Class embeddings are computed once (lazily), persisted to a JSON cache
file alongside the schema JSON-LD, and cached in-process. An asyncio
lock prevents duplicate work when multiple coroutines start up concurrently.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from openai import AsyncOpenAI

from ..config import get_embedding_api_key, get_embedding_base_url, get_embedding_model

if TYPE_CHECKING:
    from ..schema_org import SchemaOrgOntology

logger = logging.getLogger(__name__)

# Exclude non-entity Schema.org classes from the retrieval index.
# Actions describe behaviors; Enumerations are vocabulary values — neither
# is an extractable named entity.
_EXCLUDED_PARENTS = {"Action", "Enumeration", "StructuredValue", "DataType"}

# Limit concurrent embedding API requests to avoid rate-limiting
_EMBED_CONCURRENCY = 5
_embed_semaphore: asyncio.Semaphore | None = None

# Global lock to prevent concurrent embed_classes() initialisation
_embed_classes_lock: asyncio.Lock | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _embed_semaphore
    if _embed_semaphore is None:
        _embed_semaphore = asyncio.Semaphore(_EMBED_CONCURRENCY)
    return _embed_semaphore


def _get_lock() -> asyncio.Lock:
    global _embed_classes_lock
    if _embed_classes_lock is None:
        _embed_classes_lock = asyncio.Lock()
    return _embed_classes_lock


async def _embed(text: str) -> list[float]:
    """Single embedding call via OpenRouter, throttled by semaphore."""
    client = AsyncOpenAI(
        api_key=get_embedding_api_key(),
        base_url=get_embedding_base_url(),
    )
    async with _get_semaphore():
        resp = await client.embeddings.create(
            model=get_embedding_model(),
            input=text,
            encoding_format="float",
        )
    return resp.data[0].embedding


def _is_excluded(name: str, onto: SchemaOrgOntology) -> bool:
    """Return True if the class or any of its ancestors is in _EXCLUDED_PARENTS."""
    visited: set[str] = set()
    queue = [name]
    while queue:
        current = queue.pop()
        if current in visited:
            continue
        visited.add(current)
        if current in _EXCLUDED_PARENTS:
            return True
        info = onto._classes.get(current)
        if info:
            queue.extend(info.parents)
    return False


def _cache_path(jsonld_path: Path) -> Path:
    """Return the disk-cache path for class embeddings alongside the schema file."""
    model_slug = get_embedding_model().replace("/", "_").replace(":", "_")
    return jsonld_path.parent / f"class_embeddings_{model_slug}.json"


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
    # Build/fetch cached class embeddings (lock prevents duplicate concurrent build)
    async with _get_lock():
        class_embs = await onto.embed_classes(_embed)

    # Embed the source text
    text_vec = np.array(await _embed(source_text), dtype=np.float32)
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
