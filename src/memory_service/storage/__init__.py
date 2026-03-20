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

import logging
from urllib.parse import urlparse

from .long_term.base_store import BaseStore, normalize_name
from .short_term.dragonfly import DragonflyClient, create_dragonfly_client
from .short_term.memory import ShortTermMemory
from .long_term.episode_store import EpisodeStore, create_episode_store
from .long_term.knowledge_store import KnowledgeStore
from .long_term.artifact_store import ArtifactStore
from .long_term.ontology_store import OntologyStore

logger = logging.getLogger(__name__)

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

    # OpenAI embeddings client
    embedding_api_key = get_embedding_api_key()
    if not embedding_api_key:
        raise RuntimeError("Embedding API key not configured")

    openai_client = AsyncOpenAI(
        api_key=embedding_api_key,
        base_url=get_embedding_base_url(),
        max_retries=0,  # Our _embed/_embed_batch retry loop handles retries
    )

    embedding_model = get_embedding_model()

    # Schema.org Ontology (loaded once, shared singleton)
    from ..ontology.schema_org import get_shared_ontology

    schema_ontology = get_shared_ontology()

    # Initialize stores
    episode_store = EpisodeStore(graph, openai_client, embedding_model)
    await episode_store.ensure_indexes()

    knowledge_store = KnowledgeStore(graph, openai_client, embedding_model)
    await knowledge_store.ensure_indexes()

    artifact_store = ArtifactStore(graph, openai_client, embedding_model)
    await artifact_store.ensure_indexes()

    ontology_store = OntologyStore(graph, openai_client, embedding_model, schema_ontology)
    await ontology_store.ensure_indexes()

    logger.info("All storage backends initialized")

    return {
        "dragonfly": dragonfly,
        "short_term": short_term,
        "episode_store": episode_store,
        "knowledge_store": knowledge_store,
        "artifact_store": artifact_store,
        "ontology_store": ontology_store,
        "openai_client": openai_client,
    }
