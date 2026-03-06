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
    return s.get("embeddings.model", "qwen/qwen3-embedding-8b")


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
    return s.get("llm.flash_model", "google/gemini-2.5-flash-lite")


def get_llm_base_url() -> str:
    s = get_settings()
    return s.get("llm.base_url", "https://openrouter.ai/api/v1")


def get_llm_api_key() -> str:
    s = get_settings()
    return os.environ.get(
        "MEMORY_SERVICE_LLM__API_KEY",
        s.get("llm.api_key", ""),
    )


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
