"""
Simple async LLM client for the memory service.

Uses OpenAI-compatible API (OpenRouter by default).
No provider registry — the memory service only needs a single LLM endpoint.

Captures LLM reasoning traces (e.g. MiniMax <think> blocks) into a
per-group buffer for downstream metacognition.
"""

import logging
import re
import threading
from collections import defaultdict
from typing import Any, List, Dict, Optional

from openai import AsyncOpenAI

from ...config import get_llm_api_key, get_llm_base_url, get_flash_model

logger = logging.getLogger(__name__)

# Module-level singleton (initialized lazily)
_client: Optional[AsyncOpenAI] = None

# ── Reasoning trace buffer (per group_id) ─────────────────────────────
# Each entry: {"caller": <function name>, "prompt_snippet": ..., "reasoning": ...}
_reasoning_buffer: Dict[str, List[Dict[str, str]]] = defaultdict(list)
_reasoning_lock = threading.Lock()

_THINK_RE = re.compile(r"<think>([\s\S]*?)</think>")
_MAX_TRACES_PER_GROUP = 200


def capture_reasoning(group_id: str, caller: str, prompt_snippet: str, raw_text: str) -> str:
    """Extract <think> blocks from raw_text, buffer them, return cleaned text."""
    matches = _THINK_RE.findall(raw_text)
    if matches:
        reasoning = "\n".join(m.strip() for m in matches if m.strip())
        if reasoning:
            with _reasoning_lock:
                buf = _reasoning_buffer[group_id]
                if len(buf) < _MAX_TRACES_PER_GROUP:
                    buf.append({
                        "caller": caller,
                        "prompt_snippet": prompt_snippet[:200],
                        "reasoning": reasoning,
                    })
    return _THINK_RE.sub("", raw_text).strip()


def get_reasoning_traces(group_id: str) -> List[Dict[str, str]]:
    """Return and clear buffered reasoning traces for a group."""
    with _reasoning_lock:
        traces = list(_reasoning_buffer.pop(group_id, []))
    return traces


def clear_reasoning_traces(group_id: str) -> None:
    """Discard buffered reasoning traces for a group."""
    with _reasoning_lock:
        _reasoning_buffer.pop(group_id, None)


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
    max_tokens: int = 196000,
    system_prompt: Optional[str] = None,
    group_id: Optional[str] = None,
    caller: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
) -> str:
    """
    Simple async LLM call.

    Args:
        prompt: User prompt text.
        model: Model identifier (defaults to flash model from config).
        temperature: Sampling temperature.
        max_tokens: Maximum output tokens.
        system_prompt: Optional system prompt.
        group_id: If set, reasoning traces are buffered for metacognition.
        caller: Label for the calling function (for trace attribution).
        reasoning_effort: If set (e.g. "high"), enables reasoning_split and
            sets reasoning_effort via extra_body for MiniMax.

    Returns:
        LLM response text (reasoning stripped).
    """
    client = get_llm_client()
    model = model or get_flash_model()
    # Strip provider prefixes (e.g. "minimax/MiniMax-M2.7" → "MiniMax-M2.7")
    # MiniMax API expects bare model name, not prefixed
    if "/" in model:
        model = model.split("/", 1)[-1]

    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    kwargs: Dict[str, Any] = dict(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if reasoning_effort:
        kwargs["extra_body"] = {
            "reasoning_split": True,
            "reasoning_effort": reasoning_effort,
        }

    response = await client.chat.completions.create(**kwargs)

    raw = response.choices[0].message.content or ""

    # Capture reasoning from extra_body split (returned as reasoning_content)
    reasoning_content = getattr(response.choices[0].message, "reasoning_content", None) or ""
    if group_id and reasoning_content:
        with _reasoning_lock:
            buf = _reasoning_buffer[group_id]
            if len(buf) < _MAX_TRACES_PER_GROUP:
                buf.append({
                    "caller": caller or "llm_call",
                    "prompt_snippet": prompt[:200],
                    "reasoning": reasoning_content,
                })

    if group_id:
        return capture_reasoning(group_id, caller or "llm_call", prompt[:200], raw)
    return _THINK_RE.sub("", raw).strip()
