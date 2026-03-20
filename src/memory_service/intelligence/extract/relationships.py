"""
Relationship Extraction — DSPy-powered relationship mining from text.

Extracts (subject, predicate, object) triples using Schema.org property names
as predicates. The full Schema.org reference is injected into the prompt so
the LLM can pick the most specific valid property name.

Post-extraction normalization ensures all predicates and entity types are
valid Schema.org names via SchemaOrgOntology.
"""

import logging
from typing import Any, Dict, List, Optional

import dspy

from ..llm.dspy_adapter import configure_dspy_lm, adapter
from ..signatures.relationship_signature import RelationshipExtractionSignature

logger = logging.getLogger(__name__)


def _get_ontology():
    from ...ontology.schema_org import get_shared_ontology

    return get_shared_ontology()


async def extract_relationships(
    content: str,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Extract entity relationships from text using DSPy + full Schema.org reference.

    Args:
        content: Text to extract relationships from.
        model: Flash model identifier (defaults to configured flash model).

    Returns:
        List of relationship dicts with:
          - subject: display name of subject entity
          - subject_norm: normalized name for storage (e.g., 'julia-horrocks')
          - subject_type: Schema.org class name (e.g., 'Person')
          - predicate: Schema.org property name (e.g., 'worksFor')
          - object: display name of object entity
          - object_norm: normalized name for storage
          - object_type: Schema.org class name
          - confidence: float 0.0-1.0
    """
    if not content or len(content.strip()) < 10:
        return []

    MAX_INPUT = 16000
    if len(content) > MAX_INPUT:
        content = content[:MAX_INPUT]

    onto = _get_ontology()

    try:
        lm = configure_dspy_lm(model=model, temperature=0.1, max_tokens=4096)
        predictor = dspy.Predict(RelationshipExtractionSignature)

        with dspy.context(lm=lm, adapter=adapter):
            result = await predictor.acall(
                schema_reference=onto.prompt_reference,
                source_text=content,
            )

        extraction = result.result
        relationships = []

        from ...ontology.names import normalize_name

        for rel in extraction.relationships:
            try:
                # Guard: all three core fields must be present (Optional in schema)
                if not rel.subject or not rel.object or not rel.predicate:
                    continue
                subject = str(rel.subject).strip()
                object_ = str(rel.object).strip()
                if not subject or not object_:
                    continue

                # Normalize predicate and types via full Schema.org
                predicate = onto.normalize_predicate(str(rel.predicate))
                subj_type = onto.normalize_class(str(rel.subject_type))
                obj_type = onto.normalize_class(str(rel.object_type))

                subj_norm = normalize_name(subject)
                obj_norm = normalize_name(object_)

                if not subj_norm or not obj_norm:
                    continue

                if not onto.validate_triple(subj_type, predicate, obj_type):
                    logger.debug(
                        "Dropping invalid triple: %s(%s) -[%s]-> %s(%s)",
                        subject,
                        subj_type,
                        predicate,
                        object_,
                        obj_type,
                    )
                    continue

                confidence = float(rel.confidence) if rel.confidence is not None else 1.0
                confidence = max(0.0, min(1.0, confidence))

                relationships.append(
                    {
                        "subject": subject,
                        "subject_norm": subj_norm,
                        "subject_type": subj_type,
                        "predicate": predicate,
                        "object": object_,
                        "object_norm": obj_norm,
                        "object_type": obj_type,
                        "confidence": confidence,
                    }
                )
            except Exception as item_err:
                logger.debug("Skipping malformed relationship entry: %s", item_err)

        logger.info("Extracted %d relationships via DSPy (Schema.org)", len(relationships))
        return relationships

    except Exception as e:
        logger.error("Relationship extraction failed: %s", e)
        return []
