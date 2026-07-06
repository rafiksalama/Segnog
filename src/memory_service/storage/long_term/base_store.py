"""
Base Store

Shared functionality for all FalkorDB-backed stores (EpisodeStore, KnowledgeStore, ArtifactStore).
Provides embedding generation, result parsing, and name normalization.

Embedding backends:
  - "remote" (default): OpenAI-compatible API via AsyncOpenAI client
  - "local": sentence-transformers (CPU) via embed module
"""

import json
import logging
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)

_EMBED_MAX_RETRIES = 3

# Embedding dimension for the configured model (google/embeddinggemma-300m = 768).
# Must match the model in settings.toml [embeddings].model. Every vector index is
# created with this dimension; if the model changes, all vector indexes must be rebuilt.
EMBEDDING_DIM = 768

# Filtered-ANN over-fetch factors shared by every store's vector search. queryNodes
# returns the globally nearest nodes; we over-fetch so enough survive the per-query
# post-filter (group_id / type / status / min_score). See knowledge_store.search_by_vector
# for the canonical pattern.
_VECTOR_OVERFETCH = 20
_VECTOR_MIN_K = 200


def normalize_name(name: str) -> str:
    """Normalize a label/name to lowercase, hyphenated form for consistent graph storage."""
    from ...ontology.names import normalize_name as _canonical

    return _canonical(name)


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
        openai_client,  # openai.AsyncOpenAI or None (when using local backend)
        embedding_model: str,
        group_id: str = "default",
        *,
        local_embed: bool = False,
    ):
        self._graph = graph
        self._client = openai_client
        self._model = embedding_model
        self._group_id = group_id
        self._local_embed = local_embed

    async def _embed(self, text: str) -> List[float]:
        """Generate embedding using configured backend."""
        if self._local_embed:
            from .embed import aembed_single

            return await aembed_single(text, model_name=self._model)

        import asyncio

        delay = _EMBED_RETRY_BASE_DELAY
        last_err: Exception = RuntimeError("embedding failed")
        for attempt in range(_EMBED_MAX_RETRIES):
            try:
                response = await asyncio.wait_for(
                    self._client.embeddings.create(
                        model=self._model,
                        input=text,
                        encoding_format="float",
                    ),
                    timeout=30.0,
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
        """Batch embedding for multiple entries using configured backend."""
        if self._local_embed:
            from .embed import aembed_batch

            return await aembed_batch(texts, model_name=self._model)

        import asyncio

        if not texts:
            return []
        delay = _EMBED_RETRY_BASE_DELAY
        last_err: Exception = RuntimeError("batch embedding failed")
        for attempt in range(_EMBED_MAX_RETRIES):
            try:
                response = await asyncio.wait_for(
                    self._client.embeddings.create(
                        model=self._model,
                        input=texts,
                        encoding_format="float",
                    ),
                    timeout=60.0,
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

    async def _vector_search(
        self,
        *,
        label: str,
        embedding: List[float],
        top_k: int,
        min_score: float,
        where_predicates: str = "",
        return_cols: str = "",
        params: Optional[Dict[str, Any]] = None,
        node_var: str = "n",
        min_score_op: str = ">",
        knn_k: Optional[int] = None,
        fallback_on_underdeliver: bool = True,
    ) -> List[Dict[str, Any]]:
        """Indexed vector similarity search (ANN) with a brute-force fallback.

        Tries ``db.idx.vector.queryNodes`` first (O(log n), uses the label's
        VECTOR index on ``.embedding``). The queryNodes ``score`` is a cosine
        DISTANCE; we map it back to [0,1] similarity via ``(2 - score)/2`` so the
        post-filter / ORDER / LIMIT work on the same scale every store expects.

        Falls back to a brute-force ``vec.cosineDistance`` scan when:
          - the index is missing or the call errors, OR
          - ``fallback_on_underdeliver`` is True (the default, for read paths) AND
            the filtered ANN returned fewer than ``top_k`` rows (a small group in
            a large multi-tenant graph can fall outside the over-fetch window).

        Write-path callers that only need a top-1 match (e.g. per-write dedup,
        entity resolution) pass ``fallback_on_underdeliver=False`` and rely on the
        over-fetch window alone, so a no-match result doesn't trigger a full scan
        on every write.

        Args:
            label: node label, e.g. ``"Knowledge"``. Must have a VECTOR index on
                ``.embedding`` (created in the store's ``ensure_indexes``).
            embedding: query vector, already embedded by the caller.
            top_k: number of rows to return.
            min_score: minimum similarity (post ``(2-distance)/2`` mapping).
            where_predicates: extra predicates on the node/score, e.g.
                ``"n.group_id = $group_id AND n.status <> 'refuted'"``. Joined to
                the ``min_score`` check with ``AND``. Bindings come from ``params``.
            return_cols: the RETURN body, e.g.
                ``"n.uuid AS uuid, n.content AS content, score"``.
            params: bindings referenced in ``where_predicates``. ``query_vec``,
                ``min_score`` and ``top_k`` are added automatically.
            node_var: Cypher node variable name (default ``"n"``).
            min_score_op: comparison operator for ``min_score`` (``">"`` or ``">="``).
            knn_k: override the ANN over-fetch K (default ``max(top_k*20, 200)``).
            fallback_on_underdeliver: see above.
        """
        knn = knn_k or max(top_k * _VECTOR_OVERFETCH, _VECTOR_MIN_K)
        p: Dict[str, Any] = {"query_vec": embedding, "min_score": min_score, "top_k": top_k}
        if params:
            p.update(params)
        n = node_var
        filt = (
            (where_predicates + " AND " if where_predicates else "")
            + f"score {min_score_op} $min_score"
        )
        suffix = f"WHERE {filt} RETURN {return_cols} ORDER BY score DESC LIMIT $top_k"
        ann_cypher = (
            f"CALL db.idx.vector.queryNodes('{label}', 'embedding', {int(knn)}, "
            f"vecf32($query_vec)) YIELD node AS {n}, score "
            f"WITH {n}, (2 - score)/2 AS score {suffix}"
        )
        brute_cypher = (
            f"MATCH ({n}:{label}) "
            f"WITH {n}, (2 - vec.cosineDistance({n}.embedding, "
            f"vecf32($query_vec)))/2 AS score {suffix}"
        )

        try:
            result = await self._graph.ro_query(ann_cypher, params=p)
            got = len(result.result_set) if result and result.result_set else 0
            if got >= top_k or not fallback_on_underdeliver:
                return self._parse_results(result)
            logger.debug(
                "ANN under-delivered on %s (%d < %d); brute-force fallback",
                label, got, top_k,
            )
        except Exception as e:
            logger.debug(
                "Vector index search unavailable on %s (%s); brute-force scan",
                label, e,
            )
        result = await self._graph.ro_query(brute_cypher, params=p)
        return self._parse_results(result)
