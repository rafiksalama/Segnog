"""
Intelligence — stateless LLM-powered memory operations.

Responsibility: All LLM inference: extraction, reflection, synthesis,
compression, reinterpretation, judgment. Every function is a pure async
transform — no persistent state, no direct DB access.

Allowed imports: ontology/ (Schema.org vocabulary, normalize_name).
Must NOT import from: storage/, services/, workers/, messaging/, transport/.

Sub-packages:
  extract/    — mine structured facts from text
  synthesis/  — generate, compress, and summarize memory content
  evaluation/ — judge, filter, classify, and reinterpret content
  graph/      — Schema.org ontology operations (class retrieval, node updates)
  llm/        — LLM client adapters (DSPy, raw HTTP)
  signatures/ — DSPy prompt signatures
"""

from .evaluation.reinterpret import reinterpret_task
from .evaluation.filter import filter_memory_results
from .evaluation.infer_state import infer_state
from .synthesis.synthesize import synthesize_background
from .synthesis.reflect import generate_reflection, generate_metacognition
from .extract.knowledge import extract_knowledge
from .extract.artifacts import extract_artifacts
from .synthesis.compress import compress_events

__all__ = [
    "reinterpret_task",
    "filter_memory_results",
    "infer_state",
    "synthesize_background",
    "generate_reflection",
    "generate_metacognition",
    "extract_knowledge",
    "extract_artifacts",
    "compress_events",
]
