"""
Service handler — thin gRPC adapter over MemoryService.

Translates gRPC-style dict requests into typed MemoryService calls
and formats results back as dicts for the gRPC transport.
"""

import json
import logging
import time

from ...services.memory_service import MemoryService

logger = logging.getLogger(__name__)


class MemoryServiceHandler:
    """
    Thin gRPC adapter — translates dict-in/dict-out gRPC wire format
    into typed MemoryService method calls.

    All business logic lives in MemoryService. This class only handles
    request parsing and response formatting.
    """

    def __init__(self, service: MemoryService):
        self._service = service

    def _scope(self, req: dict) -> tuple:
        """Extract (group_id, workflow_id) from a scoped gRPC request."""
        scope = req.get("scope", {})
        return scope.get("group_id", "default"), scope.get("workflow_id", "default")

    # =========================================================================
    # Events (direct dragonfly access — not part of MemoryService)
    # =========================================================================

    async def log_event(self, req: dict) -> dict:
        group_id, workflow_id = self._scope(req)
        self._service._dragonfly.set_scope(group_id=group_id, workflow_id=workflow_id)
        data = req.get("event_data_json", "{}")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {"raw": data}
        event_id = await self._service._dragonfly.log_event(
            req.get("event_type", "observation"), data
        )
        return {"event_id": event_id or ""}

    async def get_recent_events(self, req: dict) -> dict:
        group_id, workflow_id = self._scope(req)
        self._service._dragonfly.set_scope(group_id=group_id, workflow_id=workflow_id)
        events = await self._service._dragonfly.get_recent_events(
            count=req.get("count", 10),
            event_type=req.get("event_type_filter") or None,
        )
        return {"events": events}

    async def search_events(self, req: dict) -> dict:
        group_id, workflow_id = self._scope(req)
        self._service._dragonfly.set_scope(group_id=group_id, workflow_id=workflow_id)
        event_types = req.get("event_types", [])
        limit = req.get("limit", 50)
        events = await self._service._dragonfly.get_recent_events(count=limit)
        if event_types:
            events = [e for e in events if e.get("type") in event_types]
        return {"events": events}

    # =========================================================================
    # Episodes
    # =========================================================================

    async def store_episode(self, req: dict) -> dict:
        group_id, _ = self._scope(req)
        metadata = req.get("metadata_json")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = None
        uuid = await self._service.store_episode(
            group_id=group_id,
            content=req.get("content", ""),
            metadata=metadata,
            episode_type=req.get("episode_type", "raw"),
        )
        return {"uuid": uuid}

    async def search_episodes(self, req: dict) -> dict:
        group_id, _ = self._scope(req)
        results = await self._service.search_episodes(
            group_id=group_id,
            query=req.get("query", ""),
            top_k=req.get("top_k", 25),
            episode_type=req.get("episode_type_filter") or None,
            min_score=req.get("min_score", 0.55),
            expand_adjacent=req.get("expand_adjacent", False),
            expansion_hops=req.get("expansion_hops", 1),
            after_time=req.get("after_time"),
            before_time=req.get("before_time"),
        )
        return {"episodes": results}

    async def link_episodes(self, req: dict) -> dict:
        group_id, _ = self._scope(req)
        success = await self._service.link_episodes(
            group_id=group_id,
            from_uuid=req.get("from_uuid", ""),
            to_uuid=req.get("to_uuid", ""),
            edge_type=req.get("edge_type", "FOLLOWS"),
            properties=req.get("properties"),
        )
        return {"linked": success}

    # =========================================================================
    # Knowledge
    # =========================================================================

    async def store_knowledge(self, req: dict) -> dict:
        group_id, _ = self._scope(req)
        uuids = await self._service.store_knowledge(
            group_id=group_id,
            entries=req.get("entries", []),
            source_mission=req.get("source_mission", ""),
            mission_status=req.get("mission_status", "success"),
            source_episode_uuid=req.get("source_episode_uuid", ""),
        )
        return {"uuids": uuids}

    async def search_knowledge(self, req: dict) -> dict:
        group_id, _ = self._scope(req)
        results = await self._service.search_knowledge(
            group_id=group_id,
            query=req.get("query", ""),
            labels=req.get("labels") or None,
            top_k=req.get("top_k", 10),
            min_score=req.get("min_score", 0.50),
            start_date=req.get("start_date"),
            end_date=req.get("end_date"),
        )
        return {"entries": results}

    async def search_by_labels(self, req: dict) -> dict:
        group_id, _ = self._scope(req)
        results = await self._service.search_knowledge_by_labels(
            group_id=group_id,
            labels=req.get("labels", []),
            top_k=req.get("top_k", 10),
        )
        return {"entries": results}

    # =========================================================================
    # Artifacts
    # =========================================================================

    async def store_artifacts(self, req: dict) -> dict:
        group_id, _ = self._scope(req)
        uuids = await self._service.store_artifacts(
            group_id=group_id,
            entries=req.get("entries", []),
            source_mission=req.get("source_mission", ""),
            mission_status=req.get("mission_status", "success"),
            source_episode_uuid=req.get("source_episode_uuid", ""),
        )
        return {"uuids": uuids}

    async def search_artifacts(self, req: dict) -> dict:
        group_id, _ = self._scope(req)
        results = await self._service.search_artifacts(
            group_id=group_id,
            query=req.get("query", ""),
            labels=req.get("labels") or None,
            top_k=req.get("top_k", 10),
            min_score=req.get("min_score", 0.45),
        )
        return {"entries": results}

    async def get_artifact(self, req: dict) -> dict:
        group_id, _ = self._scope(req)
        result = await self._service.get_artifact(
            group_id=group_id, uuid=req.get("uuid", "")
        )
        return {"artifact": result, "found": result is not None}

    async def list_recent_artifacts(self, req: dict) -> dict:
        group_id, _ = self._scope(req)
        results = await self._service.list_recent_artifacts(
            group_id=group_id, limit=req.get("limit", 50)
        )
        return {"entries": results}

    async def delete_artifact(self, req: dict) -> dict:
        group_id, _ = self._scope(req)
        existed = await self._service.delete_artifact(
            group_id=group_id, uuid=req.get("uuid", "")
        )
        return {"existed": existed}

    # =========================================================================
    # State (direct dragonfly/short_term access)
    # =========================================================================

    async def persist_execution_state(self, req: dict) -> dict:
        group_id, workflow_id = self._scope(req)
        state_key = f"exec_state:{group_id}:{workflow_id}"
        mapping = {
            "state_description": req.get("state_description", ""),
            "iteration": json.dumps(req.get("iteration", 0)),
            "updated_at": json.dumps(time.time()),
        }
        if req.get("plan_json"):
            mapping["plan"] = req["plan_json"]
        if req.get("judge_json"):
            mapping["judge"] = req["judge_json"]
        await self._service._dragonfly.hset(state_key, mapping)
        return {"success": True}

    async def get_execution_state(self, req: dict) -> dict:
        group_id, workflow_id = self._scope(req)
        state_key = f"exec_state:{group_id}:{workflow_id}"
        data = await self._service._dragonfly.hgetall(state_key)
        if not data:
            return {"found": False}
        return {
            "state_description": data.get("state_description", ""),
            "iteration": int(data.get("iteration", 0)),
            "plan_json": data.get("plan"),
            "judge_json": data.get("judge"),
            "found": True,
        }

    async def update_tool_stats(self, req: dict) -> dict:
        await self._service.update_tool_stats(
            tool_name=req.get("tool_name", ""),
            success=req.get("success", True),
            duration_ms=req.get("duration_ms", 0),
            state_description=req.get("state_description", ""),
        )
        return {"success": True}

    async def get_tool_stats(self, req: dict) -> dict:
        return await self._service.get_tool_stats()

    async def get_memory_context(self, req: dict) -> dict:
        group_id, workflow_id = self._scope(req)
        self._service._dragonfly.set_scope(group_id=group_id, workflow_id=workflow_id)
        events = await self._service._dragonfly.get_recent_events(
            count=req.get("event_limit", 5)
        )
        lines = []
        for e in reversed(events):
            etype = e.get("type", "")
            data = e.get("data", {})
            content = (
                data.get("content", str(data)[:200]) if isinstance(data, dict) else str(data)[:200]
            )
            lines.append(f"[{etype}] {content}")
        return {"formatted_context": "\n".join(lines) if lines else "No recent events."}

    # =========================================================================
    # Smart Operations (LLM-powered — stateless, no store access needed)
    # =========================================================================

    async def reinterpret_task(self, req: dict) -> dict:
        from ...intelligence.evaluation.reinterpret import reinterpret_task

        result = await reinterpret_task(
            task=req.get("task", ""), model=req.get("model") or None
        )
        return {
            "search_labels": result.get("search_labels", []),
            "search_query": result.get("search_query", ""),
            "complexity": result.get("complexity_assessment", ""),
        }

    async def filter_memory(self, req: dict) -> dict:
        from ...intelligence.evaluation.filter import filter_memory_results

        result = await filter_memory_results(
            task=req.get("task", ""),
            search_results=req.get("search_results", ""),
            model=req.get("model") or None,
            max_results=req.get("max_results", 5),
        )
        return {"filtered_results": result}

    async def infer_state_op(self, req: dict) -> dict:
        from ...intelligence.evaluation.infer_state import infer_state

        result = await infer_state(
            task=req.get("task", ""),
            retrieved_memories=req.get("retrieved_memories", ""),
            model=req.get("model") or None,
        )
        return {"state_description": result}

    async def synthesize_background_op(self, req: dict) -> dict:
        from ...intelligence.synthesis.synthesize import synthesize_background

        group_id, _ = self._scope(req)
        result = await synthesize_background(
            task=req.get("task", ""),
            long_term_context=req.get("long_term_context", ""),
            tool_stats_context=req.get("tool_stats_context", ""),
            inferred_state=req.get("state_description", ""),
            model=req.get("model") or None,
            knowledge_context=req.get("knowledge_context", ""),
            artifacts_context=req.get("artifacts_context", ""),
            episode_store=self._service._ep(group_id),
        )
        return result

    async def generate_reflection_op(self, req: dict) -> dict:
        from ...intelligence.synthesis.reflect import generate_reflection

        mission_data = req.get("mission_data_json", "{}")
        if isinstance(mission_data, str):
            mission_data = json.loads(mission_data)
        result = await generate_reflection(mission_data, model=req.get("model"))
        return {"reflection": result}

    async def extract_knowledge_op(self, req: dict) -> dict:
        from ...intelligence.extract.knowledge import extract_knowledge

        mission_data = req.get("mission_data_json", "{}")
        if isinstance(mission_data, str):
            mission_data = json.loads(mission_data)
        data_source_type = mission_data.get("data_source_type", "mission")
        entries = await extract_knowledge(
            mission_data=mission_data,
            reflection=req.get("reflection", ""),
            model=req.get("model") or None,
            data_source_type=data_source_type,
        )
        return {"entries_json": json.dumps(entries)}

    async def extract_artifacts_op(self, req: dict) -> dict:
        from ...intelligence.extract.artifacts import extract_artifacts

        mission_data = req.get("mission_data_json", "{}")
        if isinstance(mission_data, str):
            mission_data = json.loads(mission_data)
        entries = await extract_artifacts(
            mission_data=mission_data,
            model=req.get("model") or None,
        )
        return {"entries_json": json.dumps(entries)}

    async def compress_events_op(self, req: dict) -> dict:
        from ...intelligence.synthesis.compress import compress_events

        group_id, _ = self._scope(req)
        result = await compress_events(
            short_term_memory=self._service._short_term,
            episode_store=self._service._ep(group_id),
            run_id=req.get("run_id", ""),
            state_description=req.get("state_description", ""),
            model=req.get("model") or None,
        )
        return result

    # =========================================================================
    # Observe
    # =========================================================================

    async def observe(self, req: dict) -> dict:
        return await self._service.observe(
            session_id=req.get("session_id", "default"),
            content=req.get("content", ""),
            timestamp=req.get("timestamp"),
            source=req.get("source", ""),
            metadata=dict(req.get("metadata") or {}),
        )

    # =========================================================================
    # Pipelines (delegate to MemoryService)
    # =========================================================================

    async def startup_pipeline(self, req: dict) -> dict:
        group_id, workflow_id = self._scope(req)
        return await self._service.startup_pipeline(
            group_id=group_id,
            workflow_id=workflow_id,
            task=req.get("task", ""),
            model=req.get("model") or None,
        )

    async def run_curation(self, req: dict) -> dict:
        group_id, workflow_id = self._scope(req)
        mission_data_json = req.get("mission_data_json", "{}")
        if isinstance(mission_data_json, str):
            mission_data = json.loads(mission_data_json)
        else:
            mission_data = mission_data_json
        return await self._service.run_curation(
            group_id=group_id,
            workflow_id=workflow_id,
            mission_data=mission_data,
            source_episode_uuids=req.get("source_episode_uuids", []),
            model=req.get("model") or None,
        )
