"""LLM abstraction — simple async client + DSPy adapter."""

# ── Reasoning-effort fix (2026-07-07) ─────────────────────────────────────
# DSPy's dspy.LM does NOT forward ``extra_body`` to litellm.completion
# (verified: extra_body passed via dspy.LM(**kwargs) is silently dropped), so
# the ``reasoning_effort="low"`` set on MiniMax-M3 never reached the API.
# MiniMax-M3 then reasoned fully on every extraction call (~7-30s each), and
# REM consolidation jobs blew their 60s budget (10× concurrent → saturated).
#
# Inject extra_body at the litellm boundary instead: wrap litellm.completion so
# any MiniMax-M3 call that didn't ALREADY set extra_body gets reasoning_effort=
# "low" (3-5x faster, ~3-5s/call). ``client.llm_call`` sets its own extra_body
# and is left untouched. Applied at package import (before any call).
import litellm as _litellm

_orig_litellm_completion = _litellm.completion


def _low_reasoning_completion(*args, **kwargs):
    _model = str(kwargs.get("model") or (args[0] if args else ""))
    if "MiniMax-M3" in _model and "extra_body" not in kwargs:
        kwargs["extra_body"] = {"reasoning_split": True, "reasoning_effort": "low"}
    return _orig_litellm_completion(*args, **kwargs)


_litellm.completion = _low_reasoning_completion
