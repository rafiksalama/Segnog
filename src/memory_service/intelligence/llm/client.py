"""
Simple async LLM client for the memory service.

Uses OpenAI-compatible API (OpenRouter by default).
No provider registry — the memory service only needs a single LLM endpoint.
"""

import logging
from typing import List, Dict, Optional

from openai import AsyncOpenAI

from ...config import get_llm_api_key, get_llm_base_url, get_flash_model

logger = logging.getLogger(__name__)

# Module-level singleton (initialized lazily)
_client: Optional[AsyncOpenAI] = None


def get_llm_client() -> AsyncOpenAI:
    """Get or create the shared AsyncOpenAI client."""
    global _client
    if _client is None:
        api_key = get_llm_api_key()
        base_url = get_llm_base_url()
        if not api_key:
            raise RuntimeError("LLM API key not configured")
        _client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return _client


async def llm_call(
    prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    system_prompt: Optional[str] = None,
) -> str:
    """
    Simple async LLM call.

    Args:
        prompt: User prompt text.
        model: Model identifier (defaults to flash model from config).
        temperature: Sampling temperature.
        max_tokens: Maximum output tokens.
        system_prompt: Optional system prompt.

    Returns:
        LLM response text.
    """
    client = get_llm_client()
    model = model or get_flash_model()

    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    return response.choices[0].message.content or ""
