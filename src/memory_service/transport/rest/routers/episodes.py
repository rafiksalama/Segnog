"""Episodes router — store, search, and link episodes in FalkorDB."""

from fastapi import APIRouter, Query, Request

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
    do_global = body.global_search or body.group_id is None
    raw = await svc.search_episodes(
        group_id=body.group_id or "default",
        query=body.query,
        top_k=body.top_k,
        episode_type=body.episode_type_filter,
        min_score=body.min_score,
        expand_adjacent=body.expand_adjacent,
        expansion_hops=body.expansion_hops,
        after_time=body.after_time,
        before_time=body.before_time,
        global_search=do_global,
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


# Valid reflection types for filtering
_REFLECTION_TYPES = {"reflection", "metacognition", "causal_reflection"}


@router.get("/reflections")
async def list_reflections(
    request: Request,
    group_id: str = Query(""),
    reflection_type: str = Query(
        None, description="Filter by type: reflection, metacognition, causal_reflection"
    ),
    query: str = Query(None, description="Semantic search within reflections"),
    top_k: int = Query(10, ge=1, le=50),
):
    """List or search reflection episodes, optionally filtered by type.

    Reflection types:
    - reflection: structured mission analysis (what worked, what didn't)
    - metacognition: reasoning quality analysis (biases, assumptions, score)
    - causal_reflection: causal beliefs summary (cause → effect chains)
    """
    svc = get_service(request)
    gid = group_id or None

    # If a specific type is requested, use it directly; otherwise search all reflection types
    if reflection_type and reflection_type in _REFLECTION_TYPES:
        types_to_search = [reflection_type]
    else:
        types_to_search = list(_REFLECTION_TYPES)

    all_results = []
    for rtype in types_to_search:
        if query:
            raw = await svc.search_episodes(
                group_id=gid,
                query=query,
                top_k=top_k,
                episode_type=rtype,
                min_score=0.3,
                global_search=gid is None,
            )
        else:
            raw = await svc.search_episodes(
                group_id=gid,
                query=gid or "reflection",
                top_k=top_k,
                episode_type=rtype,
                min_score=0.0,
                global_search=gid is None,
            )
        for r in raw:
            all_results.append(
                {
                    "uuid": r.get("uuid", ""),
                    "reflection_type": rtype,
                    "content": r.get("content", ""),
                    "metadata": r.get("metadata"),
                    "created_at": r.get("created_at", 0.0),
                    "created_at_iso": r.get("created_at_iso"),
                    "score": r.get("score", 0.0),
                }
            )

    # Sort by score descending, then by created_at descending
    all_results.sort(key=lambda x: (-x.get("score", 0), -x.get("created_at", 0)))
    return {"reflections": all_results[:top_k]}


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
