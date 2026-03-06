"""
Entity Extraction — DSPy-powered entity mining from conversation text.

Extracts named entities (people, places, organizations, etc.) for
entity-aware memory retrieval and cross-conversation linking.
"""

import logging
from typing import Any, Dict, List, Optional

import dspy

from ..llm.dspy_adapter import configure_dspy_lm, adapter
from ..dspy_signatures.entity_signature import EntityExtractionSignature

logger = logging.getLogger(__name__)


async def extract_entities(
    content: str,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Extract named entities from conversation text using DSPy.

    Args:
        content: Text to extract entities from.
        model: Flash model identifier.

    Returns:
        List of entity dicts with name and entity_type.
    """
    if not content or len(content.strip()) < 10:
        return []

    # Cap input to avoid token overflow
    MAX_INPUT = 8000
    if len(content) > MAX_INPUT:
        content = content[:MAX_INPUT]

    try:
        lm = configure_dspy_lm(model=model, temperature=0.1, max_tokens=2048)
        predictor = dspy.Predict(EntityExtractionSignature)

        with dspy.context(lm=lm, adapter=adapter):
            result = predictor(conversation_text=content)

        extraction = result.extraction
        entities = []
        seen_names = set()
        for entry in extraction.entities:
            name = str(entry.name).strip()
            if not name or len(name) < 2:
                continue
            # Deduplicate by lowercase name
            name_lower = name.lower()
            if name_lower in seen_names:
                continue
            seen_names.add(name_lower)
            entities.append({
                "name": name,
                "entity_type": entry.entity_type,
            })

        logger.info(f"Extracted {len(entities)} entities via DSPy")
        return entities

    except Exception as e:
        logger.error(f"Entity extraction failed: {e}")
        return []
