"""Episodes router — store, search, and link episodes in FalkorDB."""

from fastapi import APIRouter, Request

from ...dto.episodes import (
    StoreEpisodeRequest,
    StoreEpisodeResponse,
    EpisodeRecord,
    SearchEpisodesRequest,
    SearchEpisodesResponse,
    LinkEpisodesRequest,
    LinkEpisodesResponse,
)
from ..dependencies import get_episode_store

router = APIRouter()


@router.post("/episodes", response_model=StoreEpisodeResponse)
async def store_episode(body: StoreEpisodeRequest, request: Request):
    store = get_episode_store(request)
    store._group_id = body.group_id
    uuid = await store.store_episode(
        content=body.content,
        metadata=body.metadata,
        episode_type=body.episode_type,
    )
    return StoreEpisodeResponse(uuid=uuid)


@router.post("/episodes/search", response_model=SearchEpisodesResponse)
async def search_episodes(body: SearchEpisodesRequest, request: Request):
    store = get_episode_store(request)
    store._group_id = body.group_id
    raw = await store.search_episodes(
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


@router.post("/episodes/link", response_model=LinkEpisodesResponse)
async def link_episodes(body: LinkEpisodesRequest, request: Request):
    store = get_episode_store(request)
    store._group_id = body.group_id
    linked = await store.link_episodes(
        from_uuid=body.from_uuid,
        to_uuid=body.to_uuid,
        edge_type=body.edge_type,
        properties=body.properties,
    )
    return LinkEpisodesResponse(linked=linked)
