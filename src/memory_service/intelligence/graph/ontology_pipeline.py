"""
Ontology Update Pipeline — Step 8 of the REM consolidation cycle.

Shared by REMWorker and CurationWorker to keep the ontology update
logic in one place. Called after curation completes for each group.

Stores results incrementally after each extraction batch — nothing is
held in memory until the end.

Two extraction passes:
  Pass 1 (per-episode, batch_size=1):  Fine-grained entity/relationship/causal extraction
  Pass 2 (multi-episode, batch_size=N): Cross-episode extraction from combined text
"""

import logging
from typing import Any, Dict, List, Optional, Set

from ...config import get_ontology_entity_max_name_words

logger = logging.getLogger(__name__)

# Schema.org types that are not real-world entities — typically image captions
_IMAGE_TYPES: frozenset = frozenset(
    {
        "Photograph",
        "ImageObject",
        "VisualArtwork",
        "Painting",
        "Drawing",
        "Sculpture",
        "CreativeWork",
    }
)


def _batch_content(batch: List[Dict[str, Any]]) -> str:
    """Join episode contents for a batch."""
    if not batch:
        return ""
    if len(batch) == 1:
        return batch[0].get("content", "")
    return "\n---\n".join(ep.get("content", "") for ep in batch if ep.get("content"))


async def _extract_and_store_batch(
    content: str,
    group_id: str,
    batch_label: str,
    ontology_store,
    causal_store,
    combined_text: str,
    seen_names: Set[str],
    ep_entity_map: Dict[str, List[str]],
    ep_uuid: Optional[str] = None,
) -> None:
    """Extract entities, relationships, and causal claims from one batch.

    Stores results immediately:
      - OntologyNodes upserted as soon as entities are extracted
      - Causal claims upserted as soon as they are extracted
      - Relationships stored after entities (needs node existence)
      - ABOUT edges created for the episode
    """
    from ..extract.entities import extract_entities
    from ..extract.relationships import extract_relationships
    from ...ontology.names import normalize_name

    if not content or len(content.strip()) < 20:
        return

    new_entity_norms: List[str] = []
    new_relationships: List[Dict[str, Any]] = []

    # ── Entities: extract → filter → upsert immediately ──
    try:
        entities = await extract_entities(content)
    except Exception as e:
        logger.error(
            "Ontology 8a [%s]: entity extraction failed for '%s': %s",
            batch_label,
            group_id,
            e,
            exc_info=True,
        )
        raise

    from .update_ontology import update_ontology_summary

    for ent in entities:
        raw_name = ent.get("name")
        if not raw_name:
            continue
        norm = normalize_name(raw_name)
        if not norm:
            continue
        if raw_name.lower() in seen_names:
            continue
        seen_names.add(raw_name.lower())

        display_name = raw_name
        schema_type = ent.get("schema_type", "Thing")

        # Skip non-entity types
        if schema_type in _IMAGE_TYPES:
            continue
        if len(display_name.split()) > get_ontology_entity_max_name_words():
            continue

        # Upsert node immediately
        try:
            existing_node = await ontology_store.get_node(norm, group_id)
            existing_summary = existing_node["summary"] if existing_node else ""

            updated_summary = await update_ontology_summary(
                entity_name=display_name,
                schema_type=schema_type,
                existing_summary=existing_summary,
                new_episode_text=combined_text,
            )

            await ontology_store.upsert_node(
                name=display_name,
                schema_type=schema_type,
                display_name=display_name,
                summary=updated_summary,
                group_id=group_id,
            )
            new_entity_norms.append(norm)
            logger.debug(
                "Ontology 8b [%s]: upserted '%s' (%s)", batch_label, display_name, schema_type
            )
        except Exception as e:
            logger.warning(
                "Ontology 8b [%s]: upsert failed for '%s': %s", batch_label, display_name, e
            )

    # ── Relationships: extract → store immediately ──
    try:
        rels = await extract_relationships(content)
        stored_rels = 0
        for rel in rels:
            try:
                ok = await ontology_store.store_relates(
                    subject_norm=rel["subject_norm"],
                    predicate=rel["predicate"],
                    object_norm=rel["object_norm"],
                    group_id=group_id,
                    confidence=rel.get("confidence", 1.0),
                )
                if ok:
                    stored_rels += 1
            except Exception:
                pass
        if stored_rels:
            logger.info(
                "Ontology 8c [%s]: stored %d/%d relationships", batch_label, stored_rels, len(rels)
            )
        new_relationships = rels
    except Exception as e:
        logger.warning("Ontology 8c [%s]: relationship extraction failed: %s", batch_label, e)

    # ── Causal claims: extract → store immediately ──
    if causal_store is not None:
        try:
            from ..extract.causals import extract_causal_claims

            claims = await extract_causal_claims(content)
            stored_claims = 0
            for claim in claims:
                try:
                    await causal_store.upsert_claim(
                        cause_summary=claim["cause"],
                        effect_summary=claim["effect"],
                        mechanism=claim.get("mechanism", ""),
                        confidence=claim.get("confidence", 0.8),
                        causal_type=claim.get("causal_type", "causes"),
                        cause_entity=claim.get("cause_norm"),
                        effect_entity=claim.get("effect_norm"),
                        group_id=group_id,
                    )
                    stored_claims += 1
                except Exception:
                    pass
            if stored_claims:
                logger.info("Ontology 8e [%s]: stored %d causal claims", batch_label, stored_claims)
        except Exception as e:
            logger.warning("Ontology 8e [%s]: causal extraction failed: %s", batch_label, e)

    # ── ABOUT edges: link episode → entities ──
    if ep_uuid and new_entity_norms:
        for norm in new_entity_norms:
            try:
                await ontology_store.link_about(ep_uuid, norm, group_id)
            except Exception:
                pass
        ep_entity_map.setdefault(ep_uuid, []).extend(new_entity_norms)

    logger.info(
        "Ontology 8 [%s]: %d entities, %d relationships, done",
        batch_label,
        len(new_entity_norms),
        len(new_relationships),
    )


async def update_group_ontology(
    ontology_store,
    group_id: str,
    episodes: List[Dict[str, Any]],
    combined_text: str,
    causal_store=None,
) -> None:
    """
    Run the full ontology update for a consolidated episode batch.

    Stores incrementally — each batch persists its results immediately.

    Two extraction passes:
      Pass 1 — per-episode (batch_size=1): fine-grained extraction
      Pass 2 — multi-episode (configurable window): cross-episode extraction
    """
    from ...config import get_ontology_extraction_window_size

    logger.info("Ontology 8: starting for group '%s' with %d episodes", group_id, len(episodes))
    window_size = get_ontology_extraction_window_size()

    seen_names: Set[str] = set()
    ep_entity_map: Dict[str, List[str]] = {}

    # ── Pass 1: Per-episode extraction ──
    for i, ep in enumerate(episodes):
        ep_uuid = ep.get("uuid")
        content = ep.get("content", "")
        label = f"pass1/ep{i}/{ep_uuid[:8] if ep_uuid else '?'}"
        await _extract_and_store_batch(
            content=content,
            group_id=group_id,
            batch_label=label,
            ontology_store=ontology_store,
            causal_store=causal_store,
            combined_text=combined_text,
            seen_names=seen_names,
            ep_entity_map=ep_entity_map,
            ep_uuid=ep_uuid,
        )

    # ── Pass 2: Multi-episode extraction (sliding window) ──
    if len(episodes) >= 2:
        for batch_start in range(0, len(episodes), window_size):
            batch = episodes[batch_start : batch_start + window_size]
            if len(batch) < 2:
                continue
            content = _batch_content(batch)
            batch_ids = "-".join(ep.get("uuid", "?")[:8] for ep in batch)
            label = f"pass2/win{batch_start // window_size}/{batch_ids}"
            await _extract_and_store_batch(
                content=content,
                group_id=group_id,
                batch_label=label,
                ontology_store=ontology_store,
                causal_store=causal_store,
                combined_text=combined_text,
                seen_names=seen_names,
                ep_entity_map=ep_entity_map,
            )

    # ── Final: revise causal beliefs ──
    if causal_store is not None:
        try:
            await causal_store.revise_beliefs(group_id)
            await causal_store.auto_chain(group_id)
        except Exception as e:
            logger.warning("Ontology 8: belief revision failed for '%s': %s", group_id, e)

    logger.info("Ontology 8: complete for group '%s'", group_id)


# ---------------------------------------------------------------------------
# Fast coverage pipeline — separate from full pipeline, no flags
# ---------------------------------------------------------------------------


async def fast_coverage_ontology(
    ontology_store,
    group_id: str,
    episodes: List[Dict[str, Any]],
    combined_text: str,
    causal_store=None,
) -> None:
    """Fast coverage pipeline: Pass 2 only, auto summaries.

    Creates OntologyNodes + RELATES edges + CausalClaims for a group.
    ABOUT edges are created separately via create_about_edges_by_similarity().
    """
    from ..extract.entities import extract_entities
    from ..extract.relationships import extract_relationships
    from ...ontology.names import normalize_name
    from ...config import get_ontology_extraction_window_size

    logger.info(
        "Fast ontology: starting for group '%s' with %d episodes",
        group_id,
        len(episodes),
    )

    window_size = get_ontology_extraction_window_size()
    seen_names: Set[str] = set()

    # Pass 2 only — no per-episode extraction
    if len(episodes) >= 2:
        for batch_start in range(0, len(episodes), window_size):
            batch = episodes[batch_start : batch_start + window_size]
            if len(batch) < 2:
                continue
            content = _batch_content(batch)
            if not content or len(content.strip()) < 20:
                continue

            label = f"fast/win{batch_start // window_size}"

            # Entities → upsert with auto-generated summary (no LLM)
            try:
                entities = await extract_entities(content)
            except Exception as e:
                logger.error("Fast ontology [%s]: entity extraction failed: %s", label, e)
                continue

            entity_count = 0
            for ent in entities:
                raw_name = ent.get("name")
                if not raw_name:
                    continue
                norm = normalize_name(raw_name)
                if not norm:
                    continue
                if raw_name.lower() in seen_names:
                    continue
                seen_names.add(raw_name.lower())

                schema_type = ent.get("schema_type", "Thing")
                if schema_type in _IMAGE_TYPES:
                    continue
                if len(raw_name.split()) > get_ontology_entity_max_name_words():
                    continue

                summary = f"{raw_name} ({schema_type})"
                try:
                    await ontology_store.upsert_node(
                        name=raw_name,
                        schema_type=schema_type,
                        display_name=raw_name,
                        summary=summary,
                        group_id=group_id,
                    )
                    entity_count += 1
                except Exception as e:
                    logger.warning(
                        "Fast ontology [%s]: upsert failed for '%s': %s", label, raw_name, e
                    )

            # Relationships → RELATES edges
            rel_count = 0
            try:
                rels = await extract_relationships(content)
                for rel in rels:
                    try:
                        ok = await ontology_store.store_relates(
                            subject_norm=rel["subject_norm"],
                            predicate=rel["predicate"],
                            object_norm=rel["object_norm"],
                            group_id=group_id,
                            confidence=rel.get("confidence", 1.0),
                        )
                        if ok:
                            rel_count += 1
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("Fast ontology [%s]: relationship extraction failed: %s", label, e)

            # Causal claims
            claim_count = 0
            if causal_store is not None:
                try:
                    from ..extract.causals import extract_causal_claims

                    claims = await extract_causal_claims(content)
                    for claim in claims:
                        try:
                            await causal_store.upsert_claim(
                                cause_summary=claim["cause"],
                                effect_summary=claim["effect"],
                                mechanism=claim.get("mechanism", ""),
                                confidence=claim.get("confidence", 0.8),
                                causal_type=claim.get("causal_type", "causes"),
                                cause_entity=claim.get("cause_norm"),
                                effect_entity=claim.get("effect_norm"),
                                group_id=group_id,
                            )
                            claim_count += 1
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning("Fast ontology [%s]: causal extraction failed: %s", label, e)

            logger.info(
                "Fast ontology [%s]: %d entities, %d relationships, %d claims",
                label,
                entity_count,
                rel_count,
                claim_count,
            )

    # Causal post-processing
    if causal_store is not None:
        try:
            await causal_store.revise_beliefs(group_id)
            await causal_store.auto_chain(group_id)
        except Exception as e:
            logger.warning("Fast ontology: belief revision failed for '%s': %s", group_id, e)

    logger.info("Fast ontology: complete for group '%s'", group_id)


async def create_about_edges_by_similarity(
    group_id: str,
    ontology_store,
    min_score: float = 0.5,
) -> int:
    """Create ABOUT edges by embedding cosine similarity (indexed ANN).

    For each episode in the group, query the OntologyNode vector index for its
    nearest ontology nodes above min_score and MERGE ABOUT edges. Replaces a
    brute-force Episode×OntologyNode cartesian product (≤20 just-consolidated
    episodes × all OntologyNodes per REM cycle) with per-episode O(log n) ANN.

    Embeddings round-trip through Python: fetched as decoded lists via the
    falkordb client, passed back as ``vecf32($ep_emb)`` params (the same pattern
    RemWorker._find_similar_consolidated already relies on).
    """
    # K must be a literal (some FalkorDB builds reject a parameter here).
    _K = 200  # over-fetch: capture every OntologyNode above min_score per episode
    graph = ontology_store._graph
    try:
        eps = await graph.ro_query(
            "MATCH (e:Episode {group_id: $group_id}) WHERE e.embedding IS NOT NULL "
            "RETURN e.uuid AS uuid, e.embedding AS embedding",
            params={"group_id": group_id},
        )
        rows = eps.result_set if eps and eps.result_set else []
    except Exception as e:
        logger.warning("Post-hoc ABOUT edges: episode fetch failed for '%s': %s", group_id, e)
        return 0

    total = 0
    for row in rows:
        ep_uuid = row[0]
        ep_emb = row[1]
        if not ep_uuid or ep_emb is None:
            continue
        try:
            res = await graph.query(
                f"CALL db.idx.vector.queryNodes('OntologyNode', 'embedding', {_K}, "
                "vecf32($ep_emb)) YIELD node AS n, score "
                "WITH n, (2 - score)/2 AS sim, $ep_uuid AS ep_uuid "
                "WHERE sim >= $min_score "
                "MATCH (e:Episode {uuid: ep_uuid}) "
                "MERGE (e)-[:ABOUT]->(n) "
                "RETURN count(*) AS c",
                params={"ep_emb": ep_emb, "ep_uuid": ep_uuid, "min_score": min_score},
            )
            if res.result_set:
                total += res.result_set[0][0] or 0
        except Exception as e:
            logger.debug("ABOUT edges for episode %s failed: %s", str(ep_uuid)[:8], e)

    if total:
        logger.info("Post-hoc ABOUT edges: %d created for group '%s'", total, group_id)
    return total
