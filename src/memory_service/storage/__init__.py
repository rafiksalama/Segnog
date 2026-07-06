"""
Storage — persistence backends.

Responsibility: All reads and writes to DragonflyDB (short-term) and FalkorDB
(long-term). No business logic, no LLM calls.

Allowed imports: ontology/ (for SchemaOrgOntology type and normalize_name).
Must NOT import from: intelligence/, services/, workers/, messaging/, transport/.

Sub-packages:
  short_term/  — DragonflyDB client and session-scoped memory
  long_term/   — FalkorDB graph stores (episodes, knowledge, artifacts, ontology)
  retrieval/   — temporal scoring and Hebbian co-activation ranking
"""

import asyncio
import logging
import os
from urllib.parse import urlparse

from .long_term.base_store import BaseStore, normalize_name
from .short_term.dragonfly import DragonflyClient, create_dragonfly_client
from .short_term.memory import ShortTermMemory
from .long_term.episode_store import EpisodeStore, create_episode_store
from .long_term.knowledge_store import KnowledgeStore
from .long_term.artifact_store import ArtifactStore
from .long_term.ontology_store import OntologyStore
from .long_term.causal_store import CausalClaimStore

logger = logging.getLogger(__name__)


def getenv_int(name: str, default: int) -> int:
    """Read a positive int from the environment, falling back to default."""
    try:
        val = int(os.getenv(name, ""))
        return val if val > 0 else default
    except (TypeError, ValueError):
        return default


# Labels that carry a vector index on .embedding. The readiness gate waits for
# every one of these to be OPERATIONAL before init_backends returns.
_VECTOR_INDEXED_LABELS = ("Knowledge", "Episode", "OntologyNode", "CausalClaim", "Artifact")


async def _await_vector_indexes(graph, timeout: int = 600, poll_interval: float = 2.0) -> None:
    """Block until every vector index is OPERATIONAL, or until timeout.

    FalkorDB rebuilds all persisted vector indexes asynchronously on each load.
    Writes (CREATE Episode + dedup from /observe) during that rebuild corrupt
    the heap (SIGSEGV). Callers run this before starting the API servers so no
    /observe can land during the rebuild window.

    On timeout we log loudly and return anyway — FalkorDB may simply be slow,
    and the per-store brute-force fallbacks keep reads correct without the
    index. A timeouted start still risks the write-during-build segfault, but
    that is strictly better than hanging startup forever on a stuck build.
    """
    expected = set(_VECTOR_INDEXED_LABELS)
    deadline = asyncio.get_event_loop().time() + timeout
    last_status: dict = {}
    while asyncio.get_event_loop().time() < deadline:
        try:
            # Cap each poll so a query hung on a saturated FalkorDB (99% CPU
            # loading the dataset) can't stall the loop — it'll time out,
            # fall through, and we retry after poll_interval.
            result = await asyncio.wait_for(
                graph.query(
                    "CALL db.indexes() YIELD label, types, status RETURN label, types, status"
                ),
                timeout=15.0,
            )
            vec_status = {}
            for row in result.result_set or []:
                label, types, status = row[0], row[1], row[2]
                if "VECTOR" in str(types):
                    vec_status[str(label)] = str(status)
            last_status = vec_status
            operational = {lbl for lbl, st in vec_status.items() if "OPERATIONAL" in st}
            if expected <= operational:
                logger.info("All vector indexes OPERATIONAL: %s", sorted(operational))
                return
            logger.info(
                "Awaiting vector index rebuild before accepting writes: %s",
                vec_status,
            )
        except Exception as e:
            # FalkorDB is typically just saturated loading the dataset here.
            logger.debug("Vector index poll failed (FalkorDB busy?): %s", e)
        await asyncio.sleep(poll_interval)
    logger.warning(
        "Vector indexes not all OPERATIONAL after %ds (last=%s); starting anyway "
        "(brute-force fallbacks remain correct). If FalkorDB is still rebuilding, "
        "this risks the write-during-build segfault — check FalkorDB stability.",
        timeout,
        last_status,
    )


__all__ = [
    "BaseStore",
    "normalize_name",
    "DragonflyClient",
    "create_dragonfly_client",
    "ShortTermMemory",
    "EpisodeStore",
    "create_episode_store",
    "KnowledgeStore",
    "ArtifactStore",
    "OntologyStore",
    "CausalClaimStore",
    "init_backends",
]


async def init_backends(session_ttl: int = 3600) -> dict:
    """Create and connect all storage backends.

    Returns dict with keys: dragonfly, short_term, episode_store,
    knowledge_store, artifact_store, ontology_store, openai_client.

    NATS wiring is intentionally excluded — callers (main.py) are responsible
    for creating NatsClient and calling episode_store.set_event_publisher().
    """
    from openai import AsyncOpenAI
    from ..config import (
        get_dragonfly_url,
        get_falkordb_url,
        get_falkordb_graph_name,
        get_embedding_model,
        get_embedding_base_url,
        get_embedding_api_key,
        get_embedding_backend,
    )

    # DragonflyDB
    dragonfly = DragonflyClient(redis_url=get_dragonfly_url(), session_ttl=session_ttl)
    if not await dragonfly.connect():
        raise RuntimeError(f"Cannot connect to DragonflyDB at {get_dragonfly_url()}")
    short_term = ShortTermMemory(dragonfly)

    # FalkorDB
    falkordb_url = get_falkordb_url()
    parsed = urlparse(falkordb_url)

    from falkordb.asyncio import FalkorDB

    db = FalkorDB(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6380,
        password=parsed.password,
    )
    graph = db.select_graph(get_falkordb_graph_name())

    # Embedding backend selection
    embedding_backend = get_embedding_backend()
    embedding_model = get_embedding_model()
    local_embed = embedding_backend == "local"

    if local_embed:
        logger.info("Using local embedding backend: %s", embedding_model)
        # Pre-load the model at startup so first request isn't slow
        from .long_term.embed import get_local_embedder

        get_local_embedder(embedding_model)
        openai_client = None  # Not needed for local backend
    else:
        embedding_api_key = get_embedding_api_key()
        if not embedding_api_key:
            raise RuntimeError("Embedding API key not configured")

        openai_client = AsyncOpenAI(
            api_key=embedding_api_key,
            base_url=get_embedding_base_url(),
            max_retries=0,  # Our _embed/_embed_batch retry loop handles retries
        )
        logger.info("Using remote embedding backend: %s", embedding_model)

    # Schema.org Ontology (loaded once, shared singleton)
    from ..ontology.schema_org import get_shared_ontology

    schema_ontology = get_shared_ontology()

    # Initialize stores
    episode_store = EpisodeStore(graph, openai_client, embedding_model, local_embed=local_embed)
    await episode_store.ensure_indexes()

    knowledge_store = KnowledgeStore(graph, openai_client, embedding_model, local_embed=local_embed)
    await knowledge_store.ensure_indexes()

    artifact_store = ArtifactStore(graph, openai_client, embedding_model, local_embed=local_embed)
    await artifact_store.ensure_indexes()

    ontology_store = OntologyStore(
        graph, openai_client, embedding_model, schema_ontology, local_embed=local_embed
    )
    await ontology_store.ensure_indexes()

    causal_store = CausalClaimStore(graph, openai_client, embedding_model, local_embed=local_embed)
    await causal_store.ensure_indexes()

    # Wait for every vector index to finish building before accepting writes.
    # FalkorDB rebuilds ALL persisted vector indexes asynchronously on every
    # load (cold start AND every restart). Concurrent /observe writes (CREATE
    # Episode + dedup) during that rebuild window corrupt FalkorDB's heap →
    # SIGSEGV restart loop (seen in production: a single index survived this
    # for weeks, 5 concurrent rebuilds + live traffic did not). Blocking here
    # keeps the REST/gRPC/MCP servers from starting — and thus from accepting
    # /observe — until every index is OPERATIONAL, so the rebuild runs
    # write-free. The per-store brute-force fallbacks keep reads correct even
    # if an index is slow to come up.
    await _await_vector_indexes(graph, timeout=getenv_int("VECTOR_INDEX_BUILD_TIMEOUT_S", 600))

    logger.info("All storage backends initialized")

    return {
        "dragonfly": dragonfly,
        "short_term": short_term,
        "episode_store": episode_store,
        "knowledge_store": knowledge_store,
        "artifact_store": artifact_store,
        "ontology_store": ontology_store,
        "causal_store": causal_store,
        "openai_client": openai_client,
    }
