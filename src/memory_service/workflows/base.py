"""Abstract workflow definition — Stage and Workflow dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional


@dataclass
class Stage:
    """A single step in a workflow.

    Args:
        name: Unique stage identifier (e.g. "reflection", "ontology").
        handler: Async callable ``(payload: dict) -> dict``.
        sync: If *True* the caller blocks until the worker replies
              (NATS request-reply).  If *False* the stage is
              fire-and-forget (NATS publish).
        depends_on: Names of stages that must complete before this one.
        timeout: Max seconds to wait for a *sync* stage.
    """

    name: str
    handler: Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]
    sync: bool = True
    depends_on: List[str] = field(default_factory=list)
    timeout: float = 60.0


@dataclass
class Workflow:
    """A DAG of :class:`Stage` objects defining an extraction pipeline.

    The :class:`WorkflowEngine` walks stages in :meth:`topological_order`
    and publishes each to its NATS pipeline queue.
    """

    name: str
    stages: List[Stage]

    # ── helpers ────────────────────────────────────────────────────────────

    def get_stage(self, name: str) -> Optional[Stage]:
        """Return a stage by name, or *None*."""
        return next((s for s in self.stages if s.name == name), None)

    def sync_stages(self) -> List[Stage]:
        """Stages that block the caller (request-reply)."""
        return [s for s in self.stages if s.sync]

    def async_stages(self) -> List[Stage]:
        """Stages that run fire-and-forget."""
        return [s for s in self.stages if not s.sync]

    def topological_order(self) -> List[Stage]:
        """Return stages sorted by dependency (Kahn's algorithm)."""
        ordered: List[Stage] = []
        visited: set[str] = set()
        visiting: set[str] = set()

        def _visit(stage: Stage) -> None:
            if stage.name in visited:
                return
            if stage.name in visiting:
                raise ValueError(f"Cycle detected in workflow '{self.name}': {stage.name}")
            visiting.add(stage.name)
            for dep_name in stage.depends_on:
                dep = self.get_stage(dep_name)
                if dep is None:
                    raise ValueError(f"Stage '{stage.name}' depends on unknown stage '{dep_name}'")
                _visit(dep)
            visiting.discard(stage.name)
            visited.add(stage.name)
            ordered.append(stage)

        for s in self.stages:
            _visit(s)
        return ordered
