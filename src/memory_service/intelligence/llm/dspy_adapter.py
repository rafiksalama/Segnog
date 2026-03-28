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

    For MiniMax: skip json_object response_format (causes <minimax:tool_call> tags).
    For OpenRouter: use json_object mode.
    """

    def __call__(self, lm, lm_kwargs, signature, demos, inputs):
        # MiniMax models don't need json_object — they produce JSON from the prompt
        model_name = getattr(lm, "model", "") or ""
        if "minimax" not in model_name.lower():
            lm_kwargs["response_format"] = {"type": "json_object"}
        return Adapter.__call__(self, lm, lm_kwargs, signature, demos, inputs)


# Singleton adapter instance
adapter = DirectJSONAdapter()


def configure_dspy_lm(
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 196000,
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

    # LiteLLM routing: openrouter needs openrouter/ prefix,
    # other OpenAI-compatible APIs use openai/ prefix
    if "openrouter" in (base_url or ""):
        litellm_model = model if model.startswith("openrouter/") else f"openrouter/{model}"
    else:
        litellm_model = model if "/" in model else f"openai/{model}"

    # Reasoning models require temperature=1.0 and higher max_tokens
    _REASONING_PREFIXES = ("openai/o1", "openai/o3", "openai/gpt-5")
    base_model = model.split("/", 1)[-1] if "/" in model else model
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
