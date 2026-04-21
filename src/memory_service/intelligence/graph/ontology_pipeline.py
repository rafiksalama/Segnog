"""
Ontology Update Pipeline — Step 8 of the REM consolidation cycle.

Shared by REMWorker and CurationWorker to keep the ontology update
logic in one place. Called after curation completes for each group.

Two extraction passes:
  Pass 1 (per-episode, batch_size=1):  Fine-grained entity/relationship/causal extraction
  Pass 2 (multi-episode, batch_size=N): Cross-episode extraction from combined text

Then:
  b) For each entity, update the OntologyNode prose summary
  c) Store relationships as RELATES edges (with inference)
  d) Link episodes to OntologyNodes via ABOUT edges
  e) Store causal claims and revise beliefs
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from ...config import get_ontology_entity_max_name_words

logger = logging.getLogger(__name__)

# Schema.org types that are not real-world entities — typically image captions
# extracted by vision models embedded in the conversation text.
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


async def _extract_from_batch(
    content: str,
    group_id: str,
    batch_label: str,
    causal_store,
    all_entities: List[Dict[str, Any]],
    all_relationships: List[Dict[str, Any]],
    all_causal_claims: List[Dict[str, Any]],
    seen_names: set,
) -> None:
    """Run entity + relationship + causal extraction on a single batch of text."""
    from ..extract.entities import extract_entities
    from ..extract.relationships import extract_relationships

    if not content or len(content.strip()) < 20:
        return

    # Entities
    try:
        entities = await extract_entities(content)
    except Exception as e:
        logger.error(
            "Ontology 8a [%s]: entity extraction failed for '%s': %s",
            batch_label, group_id, e, exc_info=True,
        )
        raise

    for ent in entities:
        name_norm = ent.get("name")
        if not name_norm:
            continue
        from ...ontology.names import normalize_name
        norm = normalize_name(name_norm)
        if not norm:
            continue
        ent["name_norm"] = norm
        if name_norm.lower() in seen_names:
            continue
        seen_names.add(name_norm.lower())
        all_entities.append(ent)

    # Relationships
    try:
        rels = await extract_relationships(content)
        all_relationships.extend(rels)
    except Exception as e:
        logger.warning("Ontology 8c [%s]: relationship extraction failed: %s", batch_label, e)

    # Causals
    if causal_store is not None:
        try:
            from ..extract.causals import extract_causal_claims
            claims = await extract_causal_claims(content)
            all_causal_claims.extend(claims)
        except Exception as e:
            logger.warning("Ontology 8e [%s]: causal extraction failed: %s", batch_label, e)

    logger.debug(
        "Ontology 8 [%s]: %d entities, %d rels, %d causals",
        batch_label, len(entities), len(rels) if 'rels' in dir() else 0, len(all_causal_claims),
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

    Two extraction passes:
      Pass 1 — per-episode (batch_size=1): fine-grained extraction
      Pass 2 — multi-episode (configurable window): cross-episode extraction

    Args:
        ontology_store: OntologyStore instance.
        group_id:       The group to update.
        episodes:       List of episode dicts with at least 'uuid' and 'content' keys.
        combined_text:  Pre-joined episode text (kept for node summary updates).
    """
    from .update_ontology import update_ontology_summary
    from ...ontology.names import normalize_name
    from ...config import get_ontology_extraction_window_size

    window_size = get_ontology_extraction_window_size()

    # Accumulators across both passes
    all_entities: List[Dict[str, Any]] = []
    all_relationships: List[Dict[str, Any]] = []
    all_causal_claims: List[Dict[str, Any]] = []
    seen_names: set = set()
    ep_entity_map: Dict[str, List[str]] = {}  # episode UUID → entity norm names

    # ----------------------------------------------------------------
    # Pass 1: Per-episode extraction (always batch_size=1)
    # ----------------------------------------------------------------
    for i, ep in enumerate(episodes):
        ep_uuid = ep.get("uuid")
        content = ep.get("content", "")
        label = f"pass1/ep{i}/{ep_uuid[:8] if ep_uuid else '?'}"
        await _extract_from_batch(
            content=content,
            group_id=group_id,
            batch_label=label,
            causal_store=causal_store,
            all_entities=all_entities,
            all_relationships=all_relationships,
            all_causal_claims=all_causal_claims,
            seen_names=seen_names,
        )
        # Map entities from this pass to the source episode
        if ep_uuid:
            ep_entity_map.setdefault(ep_uuid, []).extend(
                ent["name_norm"] for ent in all_entities if ent.get("name_norm")
            )

    # ----------------------------------------------------------------
    # Pass 2: Multi-episode extraction (sliding window)
    # ----------------------------------------------------------------
    if len(episodes) >= 2:
        for batch_start in range(0, len(episodes), window_size):
            batch = episodes[batch_start : batch_start + window_size]
            if len(batch) < 2:
                continue
            content = _batch_content(batch)
            batch_ids = "-".join(ep.get("uuid", "?")[:8] for ep in batch)
            label = f"pass2/win{batch_start//window_size}/{batch_ids}"
            await _extract_from_batch(
                content=content,
                group_id=group_id,
                batch_label=label,
                causal_store=causal_store,
                all_entities=all_entities,
                all_relationships=all_relationships,
                all_causal_claims=all_causal_claims,
                seen_names=seen_names,
            )

    if not all_entities:
        logger.debug("Ontology 8: no entities found across %d episodes for '%s'", len(episodes), group_id)
        return

    logger.info(
        "Ontology 8: extracted %d entities, %d relationships, %d causals from %d episodes for group '%s'",
        len(all_entities), len(all_relationships), len(all_causal_claims), len(episodes), group_id,
    )

    # ----------------------------------------------------------------
    # 8b. Upsert OntologyNodes with updated summaries (parallel)
    # ----------------------------------------------------------------

    async def _process_entity(entity) -> Optional[str]:
        display_name = entity["name"]
        schema_type = entity.get("schema_type", "Thing")
        name_norm = entity.get("name_norm")

        if not name_norm:
            return None

        # Skip image-description pseudo-entities
        if schema_type in _IMAGE_TYPES:
            logger.debug(
                "Ontology 8b: skipping image-type entity '%s' (%s)", display_name, schema_type
            )
            return None
        if len(display_name.split()) > get_ontology_entity_max_name_words():
            logger.debug(
                "Ontology 8b: skipping long-name entity '%s' (%d words)",
                display_name,
                len(display_name.split()),
            )
            return None

        try:
            existing_node = await ontology_store.get_node(name_norm, group_id)
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

            logger.debug(
                "Ontology 8b: upserted '%s' (%s) for group '%s'",
                display_name,
                schema_type,
                group_id,
            )
            return name_norm

        except Exception as e:
            logger.warning("Ontology 8b: upsert failed for entity '%s': %s", display_name, e)
            return None

    results = await asyncio.gather(*[_process_entity(e) for e in all_entities])
    entity_norms: List[str] = [r for r in results if r is not None]

    # ----------------------------------------------------------------
    # 8c. Store RELATES edges
    # ----------------------------------------------------------------
    stored_rels = 0
    for rel in all_relationships:
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
            else:
                logger.debug(
                    "Ontology 8c: nodes not found for (%s→%s), edge skipped",
                    rel.get("subject_norm"),
                    rel.get("object_norm"),
                )
        except Exception as e:
            logger.debug(
                "Ontology 8c: store_relates failed (%s→%s): %s",
                rel.get("subject_norm"),
                rel.get("object_norm"),
                e,
            )

    if all_relationships:
        logger.info(
            "Ontology 8c: stored %d/%d relationships for group '%s'",
            stored_rels,
            len(all_relationships),
            group_id,
        )

    # ----------------------------------------------------------------
    # 8d. Link episodes → OntologyNodes via ABOUT edges
    # ----------------------------------------------------------------
    about_count = 0
    for ep_uuid, norms in ep_entity_map.items():
        for name_norm in norms:
            try:
                await ontology_store.link_about(ep_uuid, name_norm, group_id)
                about_count += 1
            except Exception as e:
                logger.debug(
                    "Ontology 8d: link_about failed (ep=%s, entity=%s): %s",
                    ep_uuid[:8],
                    name_norm,
                    e,
                )

    if about_count:
        logger.info("Ontology 8d: created %d ABOUT edge(s) for group '%s'", about_count, group_id)

    # ----------------------------------------------------------------
    # 8e. Store causal claims + revise beliefs
    # ----------------------------------------------------------------
    if causal_store is not None and all_causal_claims:
        stored_claims = 0
        for claim in all_causal_claims:
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
            except Exception as e:
                logger.debug(
                    "Ontology 8e: upsert_claim failed (%s → %s): %s",
                    claim.get("cause"),
                    claim.get("effect"),
                    e,
                )

        logger.info(
            "Ontology 8e: stored %d/%d causal claims for group '%s'",
            stored_claims,
            len(all_causal_claims),
            group_id,
        )

        await causal_store.revise_beliefs(group_id)
        await causal_store.auto_chain(group_id)
