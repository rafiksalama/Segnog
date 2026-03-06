"""
Storage layer — extracted from GeneralAgent framework.

Provides DragonflyDB (short-term) and FalkorDB (long-term) storage backends.
"""

from .dragonfly import DragonflyClient, create_dragonfly_client
from .short_term import ShortTermMemory
from .episode_store import EpisodeStore, create_episode_store
from .knowledge_store import KnowledgeStore, normalize_label
from .artifact_store import ArtifactStore

__all__ = [
    "DragonflyClient",
    "create_dragonfly_client",
    "ShortTermMemory",
    "EpisodeStore",
    "create_episode_store",
    "KnowledgeStore",
    "normalize_label",
    "ArtifactStore",
]
