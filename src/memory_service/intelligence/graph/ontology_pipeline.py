"""
Ontology Update Pipeline — Step 8 of the REM consolidation cycle.

Shared by REMWorker and CurationWorker to keep the ontology update
logic in one place. Called after curation completes for each group.

For each batch of consolidated episodes:
  a) Extract Schema.org entities from combined episode text
  b) For each entity, update the OntologyNode prose summary
  c) Extract relationships and store as RELATES edges (with inference)
  d) Link episodes to OntologyNodes via ABOUT edges
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


async def update_group_ontology(
    ontology_store,
    group_id: str,
    episodes: List[Dict[str, Any]],
    combined_text: str,
    causal_store=None,
) -> None:
    """
    Run the full ontology update for a consolidated episode batch.

    Args:
        ontology_store: OntologyStore instance.
        group_id:       The group to update.
        episodes:       List of episode dicts with at least 'uuid' key.
        combined_text:  Pre-joined episode text (used for all LLM calls).
    """
    if not combined_text or len(combined_text.strip()) < 20:
        return

    from ..extract.entities import extract_entities
    from ..extract.relationships import extract_relationships
    from .update_ontology import update_ontology_summary
    from ...ontology.names import normalize_name

    # ----------------------------------------------------------------
    # 8a. Extract entities
    # ----------------------------------------------------------------
    try:
        entities = await extract_entities(combined_text)
    except Exception as e:
        logger.warning("Ontology Step 8a: entity extraction failed for '%s': %s", group_id, e)
        return

    if not entities:
        logger.debug("Ontology Step 8a: no entities found for '%s'", group_id)
        return

    logger.info("Ontology Step 8a: extracted %d entities for group '%s'", len(entities), group_id)

    # ----------------------------------------------------------------
    # 8b. Upsert OntologyNodes with updated summaries (parallel)
    # ----------------------------------------------------------------

    async def _process_entity(entity) -> Optional[str]:
        display_name = entity["name"]
        schema_type = entity.get("schema_type", "Thing")
        name_norm = normalize_name(display_name)

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

    results = await asyncio.gather(*[_process_entity(e) for e in entities])
    entity_norms: List[str] = [r for r in results if r is not None]

    # ----------------------------------------------------------------
    # 8c. Extract relationships → RELATES edges (with inference)
    # ----------------------------------------------------------------
    try:
        relationships = await extract_relationships(combined_text)
        stored_rels = 0
        for rel in relationships:
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

        if relationships:
            logger.info(
                "Ontology 8c: stored %d/%d relationships for group '%s'",
                stored_rels,
                len(relationships),
                group_id,
            )

    except Exception as e:
        logger.warning("Ontology 8c: relationship extraction failed for '%s': %s", group_id, e)

    # ----------------------------------------------------------------
    # 8d. Link episodes → OntologyNodes via ABOUT edges
    # ----------------------------------------------------------------
    about_count = 0
    for ep in episodes:
        ep_uuid = ep.get("uuid")
        if not ep_uuid:
            continue
        for name_norm in entity_norms:
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
    # 8e. Extract causal claims → CausalClaim nodes + entity edges
    # ----------------------------------------------------------------
    if causal_store is not None:
        try:
            from ..extract.causals import extract_causal_claims

            causal_claims = await extract_causal_claims(combined_text)
            stored_claims = 0
            for claim in causal_claims:
                try:
                    await causal_store.upsert_claim(
                        cause_summary=claim["cause"],
                        effect_summary=claim["effect"],
                        mechanism=claim.get("mechanism", ""),
                        confidence=claim.get("confidence", 0.8),
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

            if causal_claims:
                logger.info(
                    "Ontology 8e: stored %d/%d causal claims for group '%s'",
                    stored_claims,
                    len(causal_claims),
                    group_id,
                )

            # Revise belief confidences and auto-chain after new evidence
            await causal_store.revise_beliefs(group_id)
            await causal_store.auto_chain(group_id)

        except Exception as e:
            logger.warning("Ontology 8e: causal extraction failed for '%s': %s", group_id, e)
