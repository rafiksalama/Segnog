"""
Base Store

Shared functionality for all FalkorDB-backed stores (EpisodeStore, KnowledgeStore, ArtifactStore).
Provides embedding generation, result parsing, and name normalization.
"""

import json
import logging
from typing import Any, Dict, List


logger = logging.getLogger(__name__)

_EMBED_MAX_RETRIES = 3


def normalize_name(name: str) -> str:
    """Normalize a label/name to lowercase, hyphenated form for consistent graph storage."""
    import re
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")
_EMBED_RETRY_BASE_DELAY = 1.0  # seconds, doubled on each retry


class BaseStore:
    """
    Base class for FalkorDB-backed stores.

    Provides shared embedding, result parsing, and initialization.
    Subclasses: EpisodeStore, KnowledgeStore, ArtifactStore.
    """

    def __init__(
        self,
        graph,  # falkordb.asyncio.AsyncGraph
        openai_client,  # openai.AsyncOpenAI
        embedding_model: str,
        group_id: str = "default",
    ):
        self._graph = graph
        self._client = openai_client
        self._model = embedding_model
        self._group_id = group_id

    async def _embed(self, text: str) -> List[float]:
        """Generate embedding via OpenAI-compatible API with exponential-backoff retry."""
        import asyncio

        delay = _EMBED_RETRY_BASE_DELAY
        last_err: Exception = RuntimeError("embedding failed")
        for attempt in range(_EMBED_MAX_RETRIES):
            try:
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=text,
                    encoding_format="float",
                )
                return response.data[0].embedding
            except Exception as e:
                last_err = e
            if attempt < _EMBED_MAX_RETRIES - 1:
                logger.warning(
                    "_embed attempt %d/%d failed (%s); retrying in %.1fs",
                    attempt + 1,
                    _EMBED_MAX_RETRIES,
                    last_err,
                    delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
        raise last_err

    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Batch embedding for multiple entries with exponential-backoff retry."""
        import asyncio

        if not texts:
            return []
        delay = _EMBED_RETRY_BASE_DELAY
        last_err: Exception = RuntimeError("batch embedding failed")
        for attempt in range(_EMBED_MAX_RETRIES):
            try:
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=texts,
                    encoding_format="float",
                )
                return [item.embedding for item in response.data]
            except Exception as e:
                last_err = e
            if attempt < _EMBED_MAX_RETRIES - 1:
                logger.warning(
                    "_embed_batch attempt %d/%d failed (%s); retrying in %.1fs",
                    attempt + 1,
                    _EMBED_MAX_RETRIES,
                    last_err,
                    delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
        raise last_err

    def _parse_results(
        self,
        result,
        json_columns: tuple = ("labels",),
    ) -> List[Dict[str, Any]]:
        """Parse FalkorDB QueryResult into list of dicts.

        Args:
            result: FalkorDB QueryResult object.
            json_columns: Column names whose string values should be JSON-parsed.
        """
        if not result.result_set:
            return []

        columns = [h[1] if isinstance(h, (list, tuple)) else h for h in result.header]
        rows = []
        for row in result.result_set:
            record = {}
            for i, col in enumerate(columns):
                val = row[i] if i < len(row) else None
                if col in json_columns and isinstance(val, str):
                    try:
                        val = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        pass
                record[col] = val
            rows.append(record)

        return rows
