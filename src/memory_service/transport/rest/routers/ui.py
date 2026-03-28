"""UI read endpoints — lightweight data queries for the Segnog dashboard."""

import logging
from typing import Optional

from fastapi import APIRouter, Request

from ....config import (
    get_session_ttl,
    get_background_interval,
    get_background_batch_size,
    get_background_min_episodes,
    get_episode_half_life,
    get_episode_alpha,
    get_knowledge_half_life,
    get_knowledge_alpha,
    get_hebbian_learning_rate,
    get_hebbian_beta_episode,
    get_hebbian_decay_rate,
    get_hebbian_decay_interval_hours,
    get_hebbian_activation_cap,
    get_nats_enabled,
    get_nats_url,
    get_nats_curation_min_episodes,
    get_nats_curation_max_wait,
    get_nats_curation_max_concurrent,
)
from ..dependencies import get_episode_store, get_ontology_store, get_dragonfly, get_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/ui/stats")
async def get_stats(request: Request, group_id: Optional[str] = None):
    """Aggregate counts: episodes, knowledge nodes, ontology entities, groups, REM stats."""
    ep_store = get_episode_store(request)
    onto_store = get_ontology_store(request)

    gid_filter = f"{{group_id: '{group_id}'}}" if group_id else ""

    ep_count = kn_count = onto_count = grp_count = pending_count = hebbian_count = 0

    try:
        r = await ep_store._graph.ro_query(f"MATCH (e:Episode {gid_filter}) RETURN count(e) AS n")
        ep_count = r.result_set[0][0] if r.result_set else 0
    except Exception:
        pass

    try:
        r = await ep_store._graph.ro_query(f"MATCH (k:Knowledge {gid_filter}) RETURN count(k) AS n")
        kn_count = r.result_set[0][0] if r.result_set else 0
    except Exception:
        pass

    try:
        r = await onto_store._graph.ro_query(
            f"MATCH (n:OntologyNode {gid_filter}) RETURN count(n) AS n"
        )
        onto_count = r.result_set[0][0] if r.result_set else 0
    except Exception:
        pass

    try:
        r = await ep_store._graph.ro_query(
            "MATCH (e:Episode) RETURN count(DISTINCT e.group_id) AS n"
        )
        grp_count = r.result_set[0][0] if r.result_set else 0
    except Exception:
        pass

    try:
        clause = f"AND e.group_id = '{group_id}'" if group_id else ""
        r = await ep_store._graph.ro_query(
            f"MATCH (e:Episode) WHERE e.consolidation_status = 'pending' {clause} RETURN count(e) AS n"
        )
        pending_count = r.result_set[0][0] if r.result_set else 0
    except Exception:
        pass

    try:
        r = await ep_store._graph.ro_query("MATCH ()-[r:CO_ACTIVATED]->() RETURN count(r) AS n")
        hebbian_count = r.result_set[0][0] if r.result_set else 0
    except Exception:
        pass

    return {
        "episodes": ep_count,
        "knowledge_nodes": kn_count,
        "ontology_entities": onto_count,
        "active_groups": grp_count,
        "pending_episodes": pending_count,
        "hebbian_edges": hebbian_count,
    }


@router.get("/ui/sessions")
async def list_sessions(request: Request, limit: int = 200):
    """List group_ids with episode counts, latest timestamp, and parent_session_id."""
    ep_store = get_episode_store(request)
    try:
        result = await ep_store._graph.ro_query(
            """
            MATCH (e:Episode)
            WITH e.group_id AS gid, count(e) AS episode_count, max(e.created_at) AS latest_at
            OPTIONAL MATCH (s:Session {session_id: gid})
            OPTIONAL MATCH (par:Session)-[:PARENT_OF]->(s)
            RETURN gid AS group_id,
                   episode_count,
                   latest_at,
                   par.session_id AS parent_session_id
            ORDER BY latest_at DESC
            LIMIT $limit
            """,
            params={"limit": limit},
        )
        rows = [
            {
                "group_id": row[0],
                "episode_count": row[1],
                "latest_at": row[2],
                "parent_session_id": row[3],
            }
            for row in result.result_set
        ]
        return {"sessions": rows}
    except Exception as e:
        logger.warning(f"Sessions query failed: {e}")
        return {"sessions": []}


@router.get("/ui/sessions/{session_id}/children")
async def list_session_children(request: Request, session_id: str):
    """List direct child sessions of the given session."""
    ep_store = get_episode_store(request)
    try:
        result = await ep_store._graph.ro_query(
            """
            MATCH (p:Session {session_id: $sid})-[:PARENT_OF]->(c:Session)
            OPTIONAL MATCH (e:Episode {group_id: c.session_id})
            RETURN c.session_id AS group_id,
                   c.created_at AS created_at,
                   count(e) AS episode_count
            ORDER BY c.created_at DESC
            """,
            params={"sid": session_id},
        )
        rows = [
            {"group_id": row[0], "created_at": row[1], "episode_count": row[2]}
            for row in result.result_set
        ]
        return {"children": rows}
    except Exception as e:
        logger.warning(f"Children query failed: {e}")
        return {"children": []}


@router.get("/ui/episodes")
async def list_episodes(
    request: Request,
    group_id: Optional[str] = None,
    limit: int = 50,
):
    """List recent episodes without requiring a search query."""
    ep_store = get_episode_store(request)
    gid_clause = "WHERE e.group_id = $group_id" if group_id else ""
    params: dict = {"limit": limit}
    if group_id:
        params["group_id"] = group_id

    try:
        result = await ep_store._graph.ro_query(
            f"""
            MATCH (e:Episode)
            {gid_clause}
            RETURN e.uuid AS uuid,
                   e.content AS content,
                   e.episode_type AS episode_type,
                   e.group_id AS group_id,
                   e.created_at AS created_at,
                   e.created_at_iso AS created_at_iso,
                   e.consolidation_status AS consolidation_status,
                   coalesce(e.knowledge_extracted, false) AS knowledge_extracted
            ORDER BY e.created_at DESC
            LIMIT $limit
            """,
            params=params,
        )
        rows = [
            {
                "uuid": row[0],
                "content": row[1],
                "episode_type": row[2],
                "group_id": row[3],
                "created_at": row[4],
                "created_at_iso": row[5],
                "consolidated": row[6] == "consolidated",
                "knowledge_extracted": bool(row[7]),
            }
            for row in result.result_set
        ]
        return {"episodes": rows}
    except Exception as e:
        logger.warning(f"Episodes list query failed: {e}")
        return {"episodes": []}


@router.get("/ui/knowledge")
async def list_knowledge(
    request: Request,
    group_id: Optional[str] = None,
    limit: int = 50,
):
    """List recent knowledge nodes with labels."""
    ep_store = get_episode_store(request)
    gid_clause = "WHERE k.group_id = $group_id" if group_id else ""
    params: dict = {"limit": limit}
    if group_id:
        params["group_id"] = group_id

    try:
        result = await ep_store._graph.ro_query(
            f"""
            MATCH (k:Knowledge)
            {gid_clause}
            OPTIONAL MATCH (k)-[:HAS_LABEL]->(l:Label)
            RETURN k.uuid AS uuid,
                   k.content AS content,
                   k.knowledge_type AS knowledge_type,
                   k.group_id AS group_id,
                   k.confidence AS confidence,
                   k.created_at AS created_at,
                   k.event_date AS event_date,
                   collect(l.name) AS labels
            ORDER BY k.created_at DESC
            LIMIT $limit
            """,
            params=params,
        )
        rows = [
            {
                "uuid": row[0],
                "content": row[1],
                "knowledge_type": row[2],
                "group_id": row[3],
                "confidence": float(row[4]) if row[4] is not None else 0.0,
                "created_at": row[5],
                "event_date": row[6] or "",
                "labels": row[7] if isinstance(row[7], list) else [],
            }
            for row in result.result_set
        ]
        return {"knowledge": rows}
    except Exception as e:
        logger.warning(f"Knowledge list query failed: {e}")
        return {"knowledge": []}


@router.get("/ui/ontology")
async def list_ontology(
    request: Request,
    group_id: Optional[str] = None,
    schema_type: Optional[str] = None,
):
    """List ontology nodes — direct Cypher so group_id filter is optional."""
    onto_store = get_ontology_store(request)
    try:
        conditions = []
        params: dict = {}
        if group_id:
            conditions.append("n.group_id = $group_id")
            params["group_id"] = group_id
        if schema_type:
            conditions.append("n.schema_type = $schema_type")
            params["schema_type"] = schema_type
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        result = await onto_store._graph.ro_query(
            f"""
            MATCH (n:OntologyNode)
            {where}
            RETURN n.uuid AS uuid, n.name AS name, n.schema_type AS schema_type,
                   n.display_name AS display_name, n.source_count AS source_count,
                   n.updated_at AS updated_at
            ORDER BY n.updated_at DESC
            """,
            params=params,
        )
        # Compute top-level category for each schema_type using Schema.org hierarchy.
        # Category = child of Thing in ancestor chain (e.g., Hospital → Organization)
        onto = onto_store._ontology
        _cat_cache: dict = {}

        def _category(schema_type: str) -> str:
            if schema_type in _cat_cache:
                return _cat_cache[schema_type]
            chain = onto.ancestors(schema_type) if onto else [schema_type]
            # chain = [type, parent, grandparent, ..., Thing]
            # We want the element just before "Thing" (or the type itself)
            cat = schema_type
            for i, anc in enumerate(chain):
                if anc == "Thing" and i > 0:
                    cat = chain[i - 1]
                    break
            _cat_cache[schema_type] = cat
            return cat

        nodes = [
            {
                "uuid": row[0],
                "name": row[1],
                "schema_type": row[2],
                "category": _category(row[2] or "Thing"),
                "display_name": row[3] or row[1],
                "source_count": row[4] or 0,
                "updated_at": row[5],
            }
            for row in result.result_set
        ]
        return {"nodes": nodes}
    except Exception as e:
        logger.warning(f"Ontology list query failed: {e}")
        return {"nodes": []}


@router.get("/ui/causal")
async def list_causal_claims(
    request: Request,
    group_id: Optional[str] = None,
    limit: int = 50,
):
    """List causal claims with entity links and evidence counts."""
    svc = get_service(request)
    if not svc._causal_store:
        return {"claims": [], "entity_edges": []}

    store = svc._causal_store
    try:
        conditions = []
        params: dict = {"limit": limit}
        if group_id:
            conditions.append("c.group_id = $group_id")
            params["group_id"] = group_id
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        # Claims with entity links
        result = await store._graph.ro_query(
            f"""
            MATCH (c:CausalClaim)
            {where}
            OPTIONAL MATCH (c)-[:CAUSE_ENTITY]->(cause:OntologyNode)
            OPTIONAL MATCH (c)-[:EFFECT_ENTITY]->(effect:OntologyNode)
            OPTIONAL MATCH (k:Knowledge)-[s:SUPPORTS]->(c)
            OPTIONAL MATCH (k2:Knowledge)-[d:CONTRADICTS]->(c)
            RETURN c.uuid AS uuid, c.cause_summary AS cause_summary,
                   c.effect_summary AS effect_summary, c.mechanism AS mechanism,
                   c.confidence AS confidence, c.status AS status,
                   c.evidence_count AS evidence_count, c.group_id AS group_id,
                   c.created_at AS created_at,
                   cause.name AS cause_entity, cause.display_name AS cause_display,
                   effect.name AS effect_entity, effect.display_name AS effect_display,
                   count(DISTINCT s) AS support_count, count(DISTINCT d) AS contradict_count
            ORDER BY c.confidence DESC
            LIMIT $limit
            """,
            params=params,
        )
        claims = [
            {
                "uuid": row[0],
                "cause_summary": row[1],
                "effect_summary": row[2],
                "mechanism": row[3] or "",
                "confidence": float(row[4]) if row[4] is not None else 0.0,
                "status": row[5] or "active",
                "evidence_count": row[6] or 0,
                "group_id": row[7],
                "created_at": row[8],
                "cause_entity": row[9],
                "cause_display": row[10],
                "effect_entity": row[11],
                "effect_display": row[12],
                "support_count": row[13] or 0,
                "contradict_count": row[14] or 0,
            }
            for row in result.result_set
        ]

        # CAUSES edges between claims (for chain visualization)
        chain_result = await store._graph.ro_query(
            f"""
            MATCH (a:CausalClaim)-[:CAUSES]->(b:CausalClaim)
            {("WHERE a.group_id = $group_id" if group_id else "")}
            RETURN a.uuid AS from_uuid, b.uuid AS to_uuid
            LIMIT 200
            """,
            params=params,
        )
        chains = [
            {"from": row[0], "to": row[1]}
            for row in chain_result.result_set
        ]

        return {"claims": claims, "chains": chains}
    except Exception as e:
        logger.warning(f"Causal claims list query failed: {e}")
        return {"claims": [], "chains": []}


@router.get("/ui/config")
async def get_config():
    """Return all configuration values from settings.toml."""
    return {
        "scoring": {
            "episode_half_life_hours": get_episode_half_life(),
            "episode_alpha": get_episode_alpha(),
            "knowledge_half_life_hours": get_knowledge_half_life(),
            "knowledge_alpha": get_knowledge_alpha(),
        },
        "hebbian": {
            "learning_rate": get_hebbian_learning_rate(),
            "beta_episode": get_hebbian_beta_episode(),
            "decay_rate": get_hebbian_decay_rate(),
            "decay_interval_hours": get_hebbian_decay_interval_hours(),
            "activation_cap": get_hebbian_activation_cap(),
        },
        "background": {
            "interval_seconds": get_background_interval(),
            "batch_size": get_background_batch_size(),
            "min_episodes_for_processing": get_background_min_episodes(),
        },
        "session": {
            "ttl_seconds": get_session_ttl(),
        },
        "nats": {
            "enabled": str(get_nats_enabled()).lower(),
            "url": get_nats_url(),
            "curation_min_episodes": get_nats_curation_min_episodes(),
            "curation_max_wait_seconds": get_nats_curation_max_wait(),
            "curation_max_concurrent": get_nats_curation_max_concurrent(),
        },
    }


@router.get("/ui/ontology/edges")
async def list_ontology_edges(request: Request, limit: int = 300):
    """Return RELATES edges between OntologyNodes."""
    onto_store = get_ontology_store(request)
    try:
        result = await onto_store._graph.ro_query(
            """
            MATCH (a:OntologyNode)-[r:RELATES]->(b:OntologyNode)
            RETURN a.uuid AS source, b.uuid AS target, r.predicate AS predicate
            LIMIT $limit
            """,
            params={"limit": limit},
        )
        edges = [
            {"source": row[0], "target": row[1], "predicate": row[2] or ""}
            for row in result.result_set
        ]
        return {"edges": edges}
    except Exception as e:
        logger.warning(f"Ontology edges query failed: {e}")
        return {"edges": []}


@router.get("/ui/ontology/cooccurrence")
async def list_ontology_cooccurrence(request: Request, limit: int = 400):
    """
    Return pairs of OntologyNodes that co-occur in the same Episode (via ABOUT edges).
    These are implicit connections — entities that appear together in shared context.
    """
    onto_store = get_ontology_store(request)
    try:
        result = await onto_store._graph.ro_query(
            """
            MATCH (a:OntologyNode)-[:RELATES]-()
            WITH collect(DISTINCT a.uuid) AS connected
            MATCH (ep:Episode)-[:ABOUT]->(a:OntologyNode),
                  (ep)-[:ABOUT]->(b:OntologyNode)
            WHERE a.uuid < b.uuid
              AND a.uuid IN connected
              AND b.uuid IN connected
            RETURN a.uuid AS source, b.uuid AS target, count(ep) AS weight
            ORDER BY weight DESC
            LIMIT $limit
            """,
            params={"limit": limit},
        )
        edges = [
            {"source": row[0], "target": row[1], "weight": int(row[2])} for row in result.result_set
        ]
        return {"edges": edges}
    except Exception as e:
        logger.warning(f"Co-occurrence query failed: {e}")
        return {"edges": []}


@router.get("/ui/events")
async def list_events(request: Request, count: int = 20):
    """Return recent DragonflyDB stream events formatted as NATS-like subjects."""
    dragonfly = get_dragonfly(request)
    try:
        raw = await dragonfly.get_recent_events(count=count)
        events = []
        for ev in raw:
            etype = ev.get("type", "observation")
            data = ev.get("data", {}) or {}
            group = data.get("group_id", "") if isinstance(data, dict) else ""
            subj = f"memory.{etype}.{group}" if group else f"memory.{etype}"
            ts = ev.get("timestamp", "")
            events.append({"subject": subj, "time": str(ts)[:12] if ts else ""})
        return {"events": events}
    except Exception as e:
        logger.warning(f"Events query failed: {e}")
        return {"events": []}


@router.get("/ui/latency")
async def ui_latency(request: Request):
    """Per-endpoint latency stats + recent timestamped samples for realtime charts.

    Returns a list of {endpoint, count, p50, p95, p99, max, mean, samples}
    sorted by call count descending. samples is the last 60 calls ordered
    oldest-first so the dashboard can render a time-series line chart.
    """
    dragonfly = get_dragonfly(request)
    try:
        return await dragonfly.get_latency_stats()
    except Exception as e:
        logger.warning(f"Latency stats query failed: {e}")
        return []
