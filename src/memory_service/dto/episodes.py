"""Episode DTOs for REST + internal use."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class StoreEpisodeRequest(BaseModel):
    group_id: str = "default"
    content: str
    metadata: Optional[Dict[str, Any]] = None
    episode_type: str = "raw"


class StoreEpisodeResponse(BaseModel):
    uuid: str


class EpisodeRecord(BaseModel):
    uuid: str = ""
    content: str = ""
    episode_type: str = ""
    metadata: Optional[Dict[str, Any]] = None
    created_at: float = 0.0
    created_at_iso: Optional[str] = None
    score: float = 0.0
    source: Optional[str] = None  # "graph_expansion" for expanded results


class SearchEpisodesRequest(BaseModel):
    group_id: str = "default"
    query: str
    top_k: int = 25
    min_score: float = 0.55
    episode_type_filter: Optional[str] = None
    expand_adjacent: bool = False
    expansion_hops: int = 1
    after_time: Optional[float] = None
    before_time: Optional[float] = None


class SearchEpisodesResponse(BaseModel):
    episodes: List[EpisodeRecord]


class LinkEpisodesRequest(BaseModel):
    group_id: str = "default"
    from_uuid: str
    to_uuid: str
    edge_type: str = "FOLLOWS"
    properties: Optional[Dict[str, Any]] = None


class LinkEpisodesResponse(BaseModel):
    linked: bool


class SearchByEntitiesRequest(BaseModel):
    group_id: str = "default"
    entity_names: List[str]
    top_k: int = 25


class SearchByEntitiesResponse(BaseModel):
    episodes: List[EpisodeRecord]


# ── Observe API ──────────────────────────────────────────────────────────

class ObserveRequest(BaseModel):
    session_id: str
    content: str
    timestamp: Optional[str] = None  # ISO string or epoch, defaults to now
    source: Optional[str] = None     # who/what generated this observation
    metadata: Optional[Dict[str, Any]] = None
    read_only: bool = False          # If True, return context without writing
    summarize: bool = False          # If True, run LLM summarization; else return raw formatted entries
    top_k: int = 100                 # Max session entries to retrieve and score
    knowledge_top_k: int = 10       # Max knowledge entries from FalkorDB (read_only augmentation)


class ObserveResponse(BaseModel):
    episode_uuid: str = ""
    observation_type: str = "chat"
    context: str = ""                # LLM-generated context summary
    search_labels: List[str] = []    # populated on cold start (reinterpreted)
    search_query: str = ""           # populated on cold start (optimized query)
