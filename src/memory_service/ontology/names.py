"""
Entity name normalization.

Canonical key format for FalkorDB node IDs and consistent deduplication
across all layers (storage, intelligence).
"""

import re


def normalize_name(raw: str) -> str:
    """
    Normalize a name for consistent storage and deduplication.

    "Julia Horrocks" → "julia-horrocks"
    "Web Search"     → "web-search"
    "Machine Learning!" → "machine-learning"
    """
    name = raw.lower().strip()
    name = name.replace("_", "-").replace(" ", "-")
    name = re.sub(r"[^a-z0-9\-]", "", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name
