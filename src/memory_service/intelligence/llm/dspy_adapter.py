"""
DSPy adapter for the memory service.

Configures DSPy LM via LiteLLM/OpenRouter and provides
a DirectJSONAdapter that skips structured output attempts.
"""

import logging
from typing import Optional

import dspy
from dspy.adapters.json_adapter import JSONAdapter
from dspy.adapters.base import Adapter

from ...config import get_llm_api_key, get_llm_base_url, get_flash_model

logger = logging.getLogger(__name__)


class DirectJSONAdapter(JSONAdapter):
    """JSONAdapter that skips structured output and uses json_object mode directly.

    OpenRouter models don't support structured output (tool/function calling)
    through the proxy. This adapter goes straight to json_object mode.
    """

    def __call__(self, lm, lm_kwargs, signature, demos, inputs):
        lm_kwargs["response_format"] = {"type": "json_object"}
        return Adapter.__call__(self, lm, lm_kwargs, signature, demos, inputs)


# Singleton adapter instance
adapter = DirectJSONAdapter()


def configure_dspy_lm(
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    api_key: Optional[str] = None,
) -> dspy.LM:
    """
    Configure and return a DSPy LM pointing at OpenRouter.

    DSPy uses LiteLLM under the hood. OpenRouter models need
    the openrouter/ prefix so LiteLLM routes correctly.
    """
    api_key = api_key or get_llm_api_key()
    model = model or get_flash_model()
    base_url = get_llm_base_url()

    # LiteLLM needs the openrouter/ prefix
    if not model.startswith("openrouter/"):
        litellm_model = f"openrouter/{model}"
    else:
        litellm_model = model

    # Reasoning models require temperature=1.0 and higher max_tokens
    _REASONING_PREFIXES = ("openai/o1", "openai/o3", "openai/gpt-5")
    base_model = model.removeprefix("openrouter/")
    if any(base_model.startswith(p) for p in _REASONING_PREFIXES):
        temperature = 1.0
        max_tokens = max(max_tokens, 16000)

    lm = dspy.LM(
        model=litellm_model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        api_base=base_url,
    )
    return lm
