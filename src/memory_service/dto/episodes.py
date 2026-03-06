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
