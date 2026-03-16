"""
Entity Extraction — DSPy-powered entity mining from conversation text.

Extracts named entities (people, places, organizations, etc.) for
entity-aware memory retrieval and cross-conversation linking.

Now uses Schema.org class names (via SchemaOrgOntology) for entity_type,
replacing the old ad-hoc vocabulary (person, place, organization, …).
"""

import logging
from typing import Any, Dict, List, Optional

import dspy

from ..llm.dspy_adapter import configure_dspy_lm, adapter
from ..dspy_signatures.entity_signature import EntityExtractionSignature
from .class_retriever import retrieve_relevant_classes

logger = logging.getLogger(__name__)


def _get_ontology():
    from ..schema_org import get_shared_ontology

    return get_shared_ontology()


async def extract_entities(
    content: str,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Extract named entities from text using DSPy + full Schema.org reference.

    Args:
        content: Text to extract entities from.
        model: Flash model identifier (defaults to configured flash model).

    Returns:
        List of entity dicts with 'name' and 'schema_type' (Schema.org class name).
    """
    if not content or len(content.strip()) < 10:
        return []

    MAX_INPUT = 16000
    if len(content) > MAX_INPUT:
        content = content[:MAX_INPUT]

    onto = _get_ontology()

    try:
        # Retrieve top-60 Schema.org classes most relevant to this text via embedding
        relevant_classes = await retrieve_relevant_classes(content, onto, top_k=60)

        lm = configure_dspy_lm(model=model, temperature=0.1, max_tokens=4096)
        predictor = dspy.Predict(EntityExtractionSignature)

        with dspy.context(lm=lm, adapter=adapter):
            result = predictor(
                relevant_classes=relevant_classes,
                schema_reference=onto.prompt_reference,
                source_text=content,
            )

        extraction = result.extraction
        entities = []
        seen_names = set()
        for entry in extraction.entities:
            try:
                # Both fields are Optional in the model — guard against None
                if not entry.name:
                    continue
                name = str(entry.name).strip()
                if not name or len(name) < 2:
                    continue
                # Skip long-name image descriptions (> 4 words)
                if len(name.split()) > 4:
                    logger.debug("Entity extractor: skipping long-name entity '%s'", name)
                    continue
                name_lower = name.lower()
                if name_lower in seen_names:
                    continue
                seen_names.add(name_lower)

                # Normalize the schema_type against the full Schema.org
                canonical_type = onto.normalize_class(
                    str(entry.schema_type) if entry.schema_type else "Thing"
                )

                entities.append(
                    {
                        "name": name,
                        "schema_type": canonical_type,
                    }
                )
            except Exception as item_err:
                logger.debug("Entity extractor: skipping malformed entry: %s", item_err)

        logger.info("Extracted %d entities via DSPy (Schema.org)", len(entities))
        return entities

    except Exception as e:
        logger.error("Entity extraction failed: %s", e)
        return []
