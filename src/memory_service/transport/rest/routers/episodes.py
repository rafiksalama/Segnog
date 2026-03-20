"""Episodes router — store, search, and link episodes in FalkorDB."""

from fastapi import APIRouter, Request

from ..dto.episodes import (
    StoreEpisodeRequest,
    StoreEpisodeResponse,
    EpisodeRecord,
    SearchEpisodesRequest,
    SearchEpisodesResponse,
    SearchByEntitiesRequest,
    SearchByEntitiesResponse,
    LinkEpisodesRequest,
    LinkEpisodesResponse,
)
from ..dependencies import get_service

router = APIRouter()


@router.post("/episodes", response_model=StoreEpisodeResponse)
async def store_episode(body: StoreEpisodeRequest, request: Request):
    svc = get_service(request)
    uuid = await svc.store_episode(
        group_id=body.group_id,
        content=body.content,
        metadata=body.metadata,
        episode_type=body.episode_type,
    )
    return StoreEpisodeResponse(uuid=uuid)


@router.post("/episodes/search", response_model=SearchEpisodesResponse)
async def search_episodes(body: SearchEpisodesRequest, request: Request):
    svc = get_service(request)
    raw = await svc.search_episodes(
        group_id=body.group_id,
        query=body.query,
        top_k=body.top_k,
        episode_type=body.episode_type_filter,
        min_score=body.min_score,
        expand_adjacent=body.expand_adjacent,
        expansion_hops=body.expansion_hops,
        after_time=body.after_time,
        before_time=body.before_time,
    )
    episodes = [
        EpisodeRecord(
            uuid=r.get("uuid", ""),
            content=r.get("content", ""),
            episode_type=r.get("episode_type", ""),
            metadata=r.get("metadata"),
            created_at=r.get("created_at", 0.0),
            created_at_iso=r.get("created_at_iso"),
            score=r.get("score", 0.0),
            source=r.get("_source"),
        )
        for r in raw
    ]
    return SearchEpisodesResponse(episodes=episodes)


@router.post("/episodes/search/entities", response_model=SearchByEntitiesResponse)
async def search_by_entities(body: SearchByEntitiesRequest, request: Request):
    svc = get_service(request)
    raw = await svc.search_episodes_by_entities(
        group_id=body.group_id,
        entity_names=body.entity_names,
        top_k=body.top_k,
    )
    episodes = [
        EpisodeRecord(
            uuid=r.get("uuid", ""),
            content=r.get("content", ""),
            episode_type=r.get("episode_type", ""),
            metadata=r.get("metadata"),
            created_at=r.get("created_at", 0.0),
            created_at_iso=r.get("created_at_iso"),
            score=r.get("score", 0.0),
            source="entity_search",
        )
        for r in raw
    ]
    return SearchByEntitiesResponse(episodes=episodes)


@router.post("/episodes/link", response_model=LinkEpisodesResponse)
async def link_episodes(body: LinkEpisodesRequest, request: Request):
    svc = get_service(request)
    linked = await svc.link_episodes(
        group_id=body.group_id,
        from_uuid=body.from_uuid,
        to_uuid=body.to_uuid,
        edge_type=body.edge_type,
        properties=body.properties,
    )
    return LinkEpisodesResponse(linked=linked)
