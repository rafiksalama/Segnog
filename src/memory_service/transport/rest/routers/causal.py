"""Causal belief network REST endpoints."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Query, Request

from ..dependencies import get_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_causal_store(request: Request):
    svc = get_service(request)
    store = svc._causal_store
    if store is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Causal store not available")
    return store


@router.get("/causal/claims")
async def search_claims(
    request: Request,
    group_id: str = Query(...),
    query: str = Query(""),
    top_k: int = Query(5, ge=1, le=50),
):
    """Search causal claims by semantic similarity."""
    store = _get_causal_store(request)
    if query:
        embedding = await store._embed(query)
        claims = await store.search_claims(
            embedding=embedding, top_k=top_k, group_id=group_id, min_score=0.3,
        )
    else:
        claims = await store.list_claims(group_id=group_id, limit=top_k)
    return {"claims": claims}


@router.get("/causal/claims/{uuid}")
async def get_claim(uuid: str, request: Request):
    """Get a single causal claim by UUID."""
    store = _get_causal_store(request)
    claim = await store.get_claim(uuid)
    if not claim:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


@router.get("/causal/claims/{uuid}/explain")
async def explain_claim(uuid: str, request: Request):
    """Get a causal claim with its full evidence trail (SUPPORTS/CONTRADICTS)."""
    store = _get_causal_store(request)
    result = await store.explain_claim(uuid)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Claim not found")
    return result


@router.post("/causal/claims/{uuid}/evidence")
async def add_evidence(uuid: str, request: Request):
    """Add evidence for or against a causal claim.

    Body: {"knowledge_uuid": str, "direction": "supports"|"contradicts", "weight": float}
    """
    store = _get_causal_store(request)
    body = await request.json()
    knowledge_uuid = body.get("knowledge_uuid", "")
    direction = body.get("direction", "supports")
    weight = float(body.get("weight", 1.0))
    if not knowledge_uuid:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="knowledge_uuid required")
    await store.add_evidence(uuid, knowledge_uuid, direction, weight)
    # Revise beliefs after new evidence
    claim = await store.get_claim(uuid)
    group_id = claim.get("group_id", "") if claim else ""
    if group_id:
        await store.revise_beliefs(group_id)
    return {"status": "ok", "claim": await store.get_claim(uuid)}


@router.get("/causal/chain")
async def search_chain(
    request: Request,
    group_id: str = Query(...),
    query: str = Query(...),
):
    """Find the most relevant causal claim and traverse its CAUSES chain."""
    store = _get_causal_store(request)
    embedding = await store._embed(query)
    claims = await store.search_claims(
        embedding=embedding, top_k=1, group_id=group_id, min_score=0.3,
    )
    if not claims:
        return {"chain": []}

    # Traverse CAUSES edges forward from the seed claim
    seed_uuid = claims[0]["uuid"]
    try:
        result = await store._graph.ro_query(
            """
            MATCH path = (seed:CausalClaim {uuid: $uuid})-[:CAUSES*0..10]->(c:CausalClaim)
            RETURN c.uuid AS uuid, c.cause_summary AS cause_summary,
                   c.effect_summary AS effect_summary, c.mechanism AS mechanism,
                   c.confidence AS confidence, c.status AS status
            ORDER BY length(path)
            """,
            params={"uuid": seed_uuid},
        )
        chain = store._parse_results(result)
    except Exception:
        chain = [claims[0]]

    return {"seed": seed_uuid, "chain": chain}
