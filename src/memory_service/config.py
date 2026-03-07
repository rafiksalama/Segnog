"""Service configuration via Dynaconf."""

import os
from functools import lru_cache

from dynaconf import Dynaconf


@lru_cache(maxsize=1)
def get_settings() -> Dynaconf:
    """Load settings from settings.toml + environment overrides."""
    # Try source tree first (development), then CWD (Docker / installed package)
    src_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if os.path.exists(os.path.join(src_root, "settings.toml")):
        root = src_root
    else:
        root = os.getcwd()
    return Dynaconf(
        settings_files=[
            os.path.join(root, "settings.toml"),
            os.path.join(root, ".secrets.toml"),
        ],
        envvar_prefix="MEMORY_SERVICE",
        environments=True,
        env="default",
    )


def get_dragonfly_url() -> str:
    s = get_settings()
    return os.environ.get(
        "MEMORY_SERVICE_DRAGONFLY__URL",
        s.get("dragonfly.url", "redis://localhost:6381"),
    )


def get_falkordb_url() -> str:
    s = get_settings()
    return os.environ.get(
        "MEMORY_SERVICE_FALKORDB__URL",
        s.get("falkordb.url", "redis://localhost:6380"),
    )


def get_falkordb_graph_name() -> str:
    s = get_settings()
    return s.get("falkordb.graph_name", "episode_store")


def get_embedding_model() -> str:
    s = get_settings()
    return s.get("embeddings.model", "qwen/qwen3-embedding-8b:nitro")


def get_embedding_base_url() -> str:
    s = get_settings()
    return s.get("embeddings.base_url", "https://openrouter.ai/api/v1")


def get_embedding_api_key() -> str:
    s = get_settings()
    return os.environ.get(
        "MEMORY_SERVICE_EMBEDDINGS__API_KEY",
        s.get("embeddings.api_key", ""),
    )


def get_grpc_port() -> int:
    s = get_settings()
    return int(s.get("grpc.port", 50051))


def get_rest_host() -> str:
    s = get_settings()
    return s.get("rest.host", "0.0.0.0")


def get_rest_port() -> int:
    s = get_settings()
    return int(s.get("rest.port", 9000))


def get_flash_model() -> str:
    s = get_settings()
    return s.get("llm.flash_model", "arcee-ai/trinity-mini")


def get_llm_base_url() -> str:
    s = get_settings()
    return s.get("llm.base_url", "https://openrouter.ai/api/v1")


def get_llm_api_key() -> str:
    s = get_settings()
    return os.environ.get(
        "MEMORY_SERVICE_LLM__API_KEY",
        s.get("llm.api_key", ""),
    )


# Session (short-term memory)
def get_session_ttl() -> int:
    s = get_settings()
    return int(s.get("session.ttl_seconds", 3600))


# Background worker (REM sleep)
def get_background_enabled() -> bool:
    s = get_settings()
    return bool(s.get("background.enabled", False))


def get_background_interval() -> int:
    s = get_settings()
    return int(s.get("background.interval_seconds", 60))


def get_background_batch_size() -> int:
    s = get_settings()
    return int(s.get("background.batch_size", 5))


def get_background_min_episodes() -> int:
    s = get_settings()
    return int(s.get("background.min_episodes_for_processing", 3))


# Temporal scoring
def get_session_half_life() -> float:
    s = get_settings()
    return float(s.get("scoring.session_half_life_hours", 0.5))


def get_session_alpha() -> float:
    s = get_settings()
    return float(s.get("scoring.session_alpha", 0.3))


def get_episode_half_life() -> float:
    s = get_settings()
    return float(s.get("scoring.episode_half_life_hours", 168.0))


def get_episode_alpha() -> float:
    s = get_settings()
    return float(s.get("scoring.episode_alpha", 0.2))


def get_knowledge_half_life() -> float:
    s = get_settings()
    return float(s.get("scoring.knowledge_half_life_hours", 720.0))


def get_knowledge_alpha() -> float:
    s = get_settings()
    return float(s.get("scoring.knowledge_alpha", 0.1))


# Hebbian learning
def get_hebbian_enabled() -> bool:
    s = get_settings()
    return bool(s.get("hebbian.enabled", False))


def get_hebbian_learning_rate() -> float:
    s = get_settings()
    return float(s.get("hebbian.learning_rate", 0.1))


def get_hebbian_beta_episode() -> float:
    s = get_settings()
    return float(s.get("hebbian.beta_episode", 0.1))


def get_hebbian_beta_knowledge() -> float:
    s = get_settings()
    return float(s.get("hebbian.beta_knowledge", 0.05))


def get_hebbian_max_pairs() -> int:
    s = get_settings()
    return int(s.get("hebbian.max_co_activation_pairs", 15))


def get_hebbian_decay_rate() -> float:
    s = get_settings()
    return float(s.get("hebbian.decay_rate", 0.01))


def get_hebbian_decay_interval_hours() -> float:
    s = get_settings()
    return float(s.get("hebbian.decay_interval_hours", 168))


def get_hebbian_activation_cap() -> int:
    s = get_settings()
    return int(s.get("hebbian.activation_cap", 1000))
