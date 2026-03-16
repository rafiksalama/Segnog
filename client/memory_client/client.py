"""
MemoryClient — unified async client for the Agent Memory Service.

Supports both gRPC and REST transports.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryClient:
    """
    Async client for the Agent Memory Service.

    Supports gRPC and REST transports. All methods are async.

    Usage:
        # gRPC transport
        client = await MemoryClient.grpc("localhost:50051", group_id="my-agent")

        # REST transport
        client = await MemoryClient.rest("http://localhost:9000", group_id="my-agent")

        # Use it
        await client.log_event("observation", {"content": "hello"})
        uuid = await client.store_episode("Agent completed task X")
        results = await client.search_episodes("task X")

        await client.close()
    """

    def __init__(self, transport, group_id: str = "default", workflow_id: str = "default"):
        self._transport = transport
        self._group_id = group_id
        self._workflow_id = workflow_id
        self._transport_type = type(transport).__name__

    @classmethod
    async def grpc(
        cls,
        address: str,
        group_id: str = "default",
        workflow_id: str = "default",
    ) -> "MemoryClient":
        """Create a MemoryClient with gRPC transport."""
        from .grpc_transport import GrpcTransport

        transport = GrpcTransport(address)
        await transport.connect()
        return cls(transport, group_id=group_id, workflow_id=workflow_id)

    @classmethod
    async def rest(
        cls,
        base_url: str,
        group_id: str = "default",
        workflow_id: str = "default",
    ) -> "MemoryClient":
        """Create a MemoryClient with REST transport."""
        from .rest_transport import RestTransport

        transport = RestTransport(base_url)
        return cls(transport, group_id=group_id, workflow_id=workflow_id)

    async def close(self) -> None:
        """Close the transport."""
        await self._transport.close()

    def set_scope(self, group_id: str = None, workflow_id: str = None) -> None:
        """Update scope for subsequent calls."""
        if group_id:
            self._group_id = group_id
        if workflow_id:
            self._workflow_id = workflow_id

    @property
    def _scope(self) -> Dict[str, str]:
        return {"group_id": self._group_id, "workflow_id": self._workflow_id}

    # =========================================================================
    # Events
    # =========================================================================

    async def log_event(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        context: Optional[str] = None,
    ) -> str:
        """Log an event. Returns event_id."""
        if self._is_grpc:
            resp = await self._transport.call(
                "LogEvent",
                {
                    "scope": self._scope,
                    "event_type": event_type,
                    "event_data_json": json.dumps(event_data),
                    "context": context or "",
                },
            )
            return resp.get("event_id", "")
        else:
            resp = await self._transport.post(
                "/events",
                {
                    "group_id": self._group_id,
                    "workflow_id": self._workflow_id,
                    "event_type": event_type,
                    "event_data": event_data,
                    "context": context,
                },
            )
            return resp.get("event_id", "")

    async def get_recent_events(
        self,
        count: int = 10,
        event_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent events."""
        if self._is_grpc:
            resp = await self._transport.call(
                "GetRecentEvents",
                {
                    "scope": self._scope,
                    "count": count,
                    "event_type_filter": event_type or "",
                },
            )
            return resp.get("events", [])
        else:
            params = {
                "group_id": self._group_id,
                "workflow_id": self._workflow_id,
                "count": count,
            }
            if event_type:
                params["event_type"] = event_type
            resp = await self._transport.get("/events/recent", params=params)
            return resp.get("events", [])

    # =========================================================================
    # Episodes
    # =========================================================================

    async def store_episode(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        episode_type: str = "raw",
    ) -> str:
        """Store an episode. Returns UUID."""
        if self._is_grpc:
            resp = await self._transport.call(
                "StoreEpisode",
                {
                    "scope": self._scope,
                    "content": content,
                    "metadata_json": json.dumps(metadata or {}),
                    "episode_type": episode_type,
                },
            )
            return resp.get("uuid", "")
        else:
            resp = await self._transport.post(
                "/episodes",
                {
                    "group_id": self._group_id,
                    "content": content,
                    "metadata": metadata,
                    "episode_type": episode_type,
                },
            )
            return resp.get("uuid", "")

    async def search_episodes(
        self,
        query: str,
        top_k: int = 20,
        min_score: float = 0.55,
        episode_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search episodes by vector similarity."""
        if self._is_grpc:
            resp = await self._transport.call(
                "SearchEpisodes",
                {
                    "scope": self._scope,
                    "query": query,
                    "top_k": top_k,
                    "min_score": min_score,
                    "episode_type_filter": episode_type or "",
                },
            )
            return resp.get("episodes", [])
        else:
            resp = await self._transport.post(
                "/episodes/search",
                {
                    "group_id": self._group_id,
                    "query": query,
                    "top_k": top_k,
                    "min_score": min_score,
                    "episode_type_filter": episode_type,
                },
            )
            return resp.get("episodes", [])

    # =========================================================================
    # Knowledge
    # =========================================================================

    async def store_knowledge(
        self,
        entries: List[Dict[str, Any]],
        source_mission: str,
        mission_status: str = "success",
        source_episode_uuid: str = "",
    ) -> List[str]:
        """Store knowledge entries. Returns list of UUIDs."""
        if self._is_grpc:
            resp = await self._transport.call(
                "StoreKnowledge",
                {
                    "scope": self._scope,
                    "entries": entries,
                    "source_mission": source_mission,
                    "mission_status": mission_status,
                    "source_episode_uuid": source_episode_uuid,
                },
            )
            return resp.get("uuids", [])
        else:
            resp = await self._transport.post(
                "/knowledge",
                {
                    "group_id": self._group_id,
                    "entries": entries,
                    "source_mission": source_mission,
                    "mission_status": mission_status,
                    "source_episode_uuid": source_episode_uuid,
                },
            )
            return resp.get("uuids", [])

    async def search_knowledge(
        self,
        query: str,
        labels: Optional[List[str]] = None,
        top_k: int = 10,
        min_score: float = 0.50,
    ) -> List[Dict[str, Any]]:
        """Hybrid search: vector + label boosting."""
        if self._is_grpc:
            resp = await self._transport.call(
                "SearchKnowledge",
                {
                    "scope": self._scope,
                    "query": query,
                    "labels": labels or [],
                    "top_k": top_k,
                    "min_score": min_score,
                },
            )
            return resp.get("entries", [])
        else:
            resp = await self._transport.post(
                "/knowledge/search",
                {
                    "group_id": self._group_id,
                    "query": query,
                    "labels": labels or [],
                    "top_k": top_k,
                    "min_score": min_score,
                },
            )
            return resp.get("entries", [])

    async def search_knowledge_by_labels(
        self,
        labels: List[str],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Label-only search."""
        if self._is_grpc:
            resp = await self._transport.call(
                "SearchByLabels",
                {
                    "scope": self._scope,
                    "labels": labels,
                    "top_k": top_k,
                },
            )
            return resp.get("entries", [])
        else:
            resp = await self._transport.post(
                "/knowledge/search-labels",
                {
                    "group_id": self._group_id,
                    "labels": labels,
                    "top_k": top_k,
                },
            )
            return resp.get("entries", [])

    # =========================================================================
    # Artifacts
    # =========================================================================

    async def store_artifacts(
        self,
        entries: List[Dict[str, Any]],
        source_mission: str,
        mission_status: str = "success",
        source_episode_uuid: str = "",
    ) -> List[str]:
        """Store artifacts. Returns list of UUIDs."""
        if self._is_grpc:
            resp = await self._transport.call(
                "StoreArtifacts",
                {
                    "scope": self._scope,
                    "entries": entries,
                    "source_mission": source_mission,
                    "mission_status": mission_status,
                    "source_episode_uuid": source_episode_uuid,
                },
            )
            return resp.get("uuids", [])
        else:
            resp = await self._transport.post(
                "/artifacts",
                {
                    "group_id": self._group_id,
                    "entries": entries,
                    "source_mission": source_mission,
                    "mission_status": mission_status,
                    "source_episode_uuid": source_episode_uuid,
                },
            )
            return resp.get("uuids", [])

    async def search_artifacts(
        self,
        query: str,
        labels: Optional[List[str]] = None,
        top_k: int = 10,
        min_score: float = 0.45,
    ) -> List[Dict[str, Any]]:
        """Hybrid search for artifacts."""
        if self._is_grpc:
            resp = await self._transport.call(
                "SearchArtifacts",
                {
                    "scope": self._scope,
                    "query": query,
                    "labels": labels or [],
                    "top_k": top_k,
                    "min_score": min_score,
                },
            )
            return resp.get("entries", [])
        else:
            resp = await self._transport.post(
                "/artifacts/search",
                {
                    "group_id": self._group_id,
                    "query": query,
                    "labels": labels or [],
                    "top_k": top_k,
                    "min_score": min_score,
                },
            )
            return resp.get("entries", [])

    async def get_artifact(self, uuid: str) -> Optional[Dict[str, Any]]:
        """Get a single artifact by UUID."""
        if self._is_grpc:
            resp = await self._transport.call(
                "GetArtifact",
                {
                    "scope": self._scope,
                    "uuid": uuid,
                },
            )
            return resp.get("artifact") if resp.get("found") else None
        else:
            try:
                resp = await self._transport.get(
                    f"/artifacts/{uuid}",
                    params={"group_id": self._group_id},
                )
                return resp.get("artifact") if resp.get("found") else None
            except Exception:
                return None

    async def list_recent_artifacts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List recent artifacts."""
        if self._is_grpc:
            resp = await self._transport.call(
                "ListRecent",
                {
                    "scope": self._scope,
                    "limit": limit,
                },
            )
            return resp.get("entries", [])
        else:
            resp = await self._transport.get(
                "/artifacts/recent/list",
                params={"group_id": self._group_id, "limit": limit},
            )
            return resp.get("entries", [])

    async def delete_artifact(self, uuid: str) -> bool:
        """Delete an artifact by UUID."""
        if self._is_grpc:
            resp = await self._transport.call(
                "DeleteArtifact",
                {
                    "scope": self._scope,
                    "uuid": uuid,
                },
            )
            return resp.get("existed", False)
        else:
            resp = await self._transport.delete(
                f"/artifacts/{uuid}",
                params={"group_id": self._group_id},
            )
            return resp.get("existed", False)

    # =========================================================================
    # State
    # =========================================================================

    async def persist_execution_state(
        self,
        state_description: str,
        iteration: int,
        plan_json: Optional[str] = None,
        judge_json: Optional[str] = None,
    ) -> bool:
        """Persist execution state."""
        if self._is_grpc:
            resp = await self._transport.call(
                "PersistExecutionState",
                {
                    "scope": self._scope,
                    "state_description": state_description,
                    "iteration": iteration,
                    "plan_json": plan_json or "",
                    "judge_json": judge_json or "",
                },
            )
            return resp.get("success", False)
        else:
            resp = await self._transport.put(
                "/state/execution",
                {
                    "group_id": self._group_id,
                    "workflow_id": self._workflow_id,
                    "state_description": state_description,
                    "iteration": iteration,
                    "plan_json": plan_json,
                    "judge_json": judge_json,
                },
            )
            return resp.get("success", False)

    async def get_execution_state(self) -> Optional[Dict[str, Any]]:
        """Get current execution state."""
        if self._is_grpc:
            resp = await self._transport.call(
                "GetExecutionState",
                {
                    "scope": self._scope,
                },
            )
            return resp if resp.get("found") else None
        else:
            resp = await self._transport.get(
                "/state/execution",
                params={
                    "group_id": self._group_id,
                    "workflow_id": self._workflow_id,
                },
            )
            return resp if resp.get("found") else None

    async def update_tool_stats(
        self,
        tool_name: str,
        success: bool,
        duration_ms: int = 0,
        state_description: str = "",
    ) -> bool:
        """Update tool usage statistics."""
        if self._is_grpc:
            resp = await self._transport.call(
                "UpdateToolStats",
                {
                    "scope": self._scope,
                    "tool_name": tool_name,
                    "success": success,
                    "duration_ms": duration_ms,
                    "state_description": state_description,
                },
            )
            return resp.get("success", False)
        else:
            resp = await self._transport.post(
                "/state/tool-stats",
                {
                    "group_id": self._group_id,
                    "workflow_id": self._workflow_id,
                    "tool_name": tool_name,
                    "success": success,
                    "duration_ms": duration_ms,
                    "state_description": state_description,
                },
            )
            return resp.get("success", False)

    async def get_tool_stats(
        self,
        tool_names: Optional[List[str]] = None,
    ) -> str:
        """Get formatted tool statistics."""
        if self._is_grpc:
            resp = await self._transport.call(
                "GetToolStats",
                {
                    "scope": self._scope,
                    "tool_names": tool_names or [],
                },
            )
            return resp.get("formatted_stats", "")
        else:
            resp = await self._transport.get(
                "/state/tool-stats",
                params={
                    "group_id": self._group_id,
                    "workflow_id": self._workflow_id,
                },
            )
            return resp.get("formatted_stats", "")

    async def get_memory_context(self, event_limit: int = 5) -> str:
        """Get formatted memory context for prompt injection."""
        if self._is_grpc:
            resp = await self._transport.call(
                "GetMemoryContext",
                {
                    "scope": self._scope,
                    "event_limit": event_limit,
                },
            )
            return resp.get("formatted_context", "")
        else:
            resp = await self._transport.get(
                "/state/context",
                params={
                    "group_id": self._group_id,
                    "workflow_id": self._workflow_id,
                    "event_limit": event_limit,
                },
            )
            return resp.get("formatted_context", "")

    # =========================================================================
    # Observe (unified write + read)
    # =========================================================================

    async def observe(
        self,
        content: str,
        source: Optional[str] = None,
        read_only: bool = False,
        summarize: bool = False,
        top_k: int = 100,
        minimal: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Unified observe: store observation + retrieve relevant context."""
        if self._is_grpc:
            resp = await self._transport.call(
                "Observe",
                {
                    "scope": self._scope,
                    "session_id": self._workflow_id,
                    "content": content,
                    "source": source or "",
                    "metadata": metadata or {},
                },
            )
        else:
            resp = await self._transport.post(
                "/api/v1/memory/observe",
                {
                    "session_id": self._workflow_id,
                    "content": content,
                    "source": source,
                    "metadata": metadata,
                    "read_only": read_only,
                    "summarize": summarize,
                    "top_k": top_k,
                    "minimal": minimal,
                },
            )
        return resp or {}

    # =========================================================================
    # Smart Operations (Phase 2)
    # =========================================================================

    async def reinterpret_task(self, task: str, model: Optional[str] = None) -> Dict[str, Any]:
        """Reinterpret task into search labels, query, and complexity."""
        if self._is_grpc:
            return await self._transport.call(
                "ReinterpretTask",
                {
                    "task": task,
                    "model": model or "",
                },
            )
        else:
            return await self._transport.post(
                "/smart/reinterpret-task",
                {
                    "task": task,
                    "model": model,
                },
            )

    async def filter_memory_results(
        self,
        task: str,
        results: str,
        model: Optional[str] = None,
        max_results: int = 5,
    ) -> str:
        """Filter memory results for relevance."""
        if self._is_grpc:
            resp = await self._transport.call(
                "FilterMemoryResults",
                {
                    "task": task,
                    "search_results": results,
                    "model": model or "",
                    "max_results": max_results,
                },
            )
            return resp.get("filtered_results", "")
        else:
            resp = await self._transport.post(
                "/smart/filter-results",
                {
                    "task": task,
                    "search_results": results,
                    "model": model,
                    "max_results": max_results,
                },
            )
            return resp.get("filtered_results", "")

    async def infer_state(
        self,
        task: str,
        memories: str,
        model: Optional[str] = None,
    ) -> str:
        """Infer agent state from task + memories."""
        if self._is_grpc:
            resp = await self._transport.call(
                "InferState",
                {
                    "task": task,
                    "retrieved_memories": memories,
                    "model": model or "",
                },
            )
            return resp.get("state_description", "")
        else:
            resp = await self._transport.post(
                "/smart/infer-state",
                {
                    "task": task,
                    "retrieved_memories": memories,
                    "model": model,
                },
            )
            return resp.get("state_description", "")

    async def synthesize_background(
        self,
        task: str,
        long_term: str = "",
        tool_stats: str = "",
        state: str = "",
        model: Optional[str] = None,
        knowledge: str = "",
        artifacts: str = "",
    ) -> str:
        """Synthesize background narrative."""
        if self._is_grpc:
            resp = await self._transport.call(
                "SynthesizeBackground",
                {
                    "scope": self._scope,
                    "task": task,
                    "long_term_context": long_term,
                    "tool_stats_context": tool_stats,
                    "state_description": state,
                    "knowledge_context": knowledge,
                    "artifacts_context": artifacts,
                    "model": model or "",
                },
            )
            return resp.get("narrative", "")
        else:
            resp = await self._transport.post(
                "/smart/synthesize-background",
                {
                    "group_id": self._group_id,
                    "workflow_id": self._workflow_id,
                    "task": task,
                    "long_term_context": long_term,
                    "tool_stats_context": tool_stats,
                    "state_description": state,
                    "knowledge_context": knowledge,
                    "artifacts_context": artifacts,
                    "model": model,
                },
            )
            return resp.get("narrative", "")

    async def generate_reflection(self, mission_data: Dict[str, Any]) -> str:
        """Generate post-mission reflection."""
        data_json = json.dumps(mission_data)
        if self._is_grpc:
            resp = await self._transport.call(
                "GenerateReflection",
                {
                    "mission_data_json": data_json,
                },
            )
            return resp.get("reflection", "")
        else:
            resp = await self._transport.post(
                "/smart/generate-reflection",
                {
                    "mission_data_json": data_json,
                },
            )
            return resp.get("reflection", "")

    async def extract_knowledge(
        self,
        mission_data: Dict[str, Any],
        reflection: str,
        model: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Extract knowledge entries from mission data."""
        data_json = json.dumps(mission_data)
        if self._is_grpc:
            resp = await self._transport.call(
                "ExtractKnowledge",
                {
                    "mission_data_json": data_json,
                    "reflection": reflection,
                    "model": model or "",
                },
            )
        else:
            resp = await self._transport.post(
                "/smart/extract-knowledge",
                {
                    "mission_data_json": data_json,
                    "reflection": reflection,
                    "model": model,
                },
            )
        entries_json = resp.get("entries_json", "[]")
        return json.loads(entries_json) if isinstance(entries_json, str) else entries_json

    async def extract_artifacts(
        self,
        mission_data: Dict[str, Any],
        model: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Extract artifact entries from mission data."""
        data_json = json.dumps(mission_data)
        if self._is_grpc:
            resp = await self._transport.call(
                "ExtractArtifacts",
                {
                    "mission_data_json": data_json,
                    "model": model or "",
                },
            )
        else:
            resp = await self._transport.post(
                "/smart/extract-artifacts",
                {
                    "mission_data_json": data_json,
                    "model": model,
                },
            )
        entries_json = resp.get("entries_json", "[]")
        return json.loads(entries_json) if isinstance(entries_json, str) else entries_json

    async def compress_events(
        self,
        run_id: str,
        state_description: str = "",
    ) -> bool:
        """Compress old events into episode summary."""
        if self._is_grpc:
            resp = await self._transport.call(
                "CompressEvents",
                {
                    "scope": self._scope,
                    "run_id": run_id,
                    "state_description": state_description,
                },
            )
            return resp.get("compressed", False)
        else:
            resp = await self._transport.post(
                "/smart/compress-events",
                {
                    "group_id": self._group_id,
                    "workflow_id": self._workflow_id,
                    "run_id": run_id,
                    "state_description": state_description,
                },
            )
            return resp.get("compressed", False)

    # =========================================================================
    # Pipelines (Phase 3)
    # =========================================================================

    async def startup_pipeline(
        self,
        task: str,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run full startup pipeline."""
        if self._is_grpc:
            return await self._transport.call(
                "StartupPipeline",
                {
                    "scope": self._scope,
                    "task": task,
                    "model": model or "",
                },
            )
        else:
            return await self._transport.post(
                "/pipelines/startup",
                {
                    "group_id": self._group_id,
                    "workflow_id": self._workflow_id,
                    "task": task,
                    "model": model,
                },
            )

    async def run_curation(
        self,
        mission_data: Dict[str, Any],
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run full curation pipeline."""
        if self._is_grpc:
            return await self._transport.call(
                "RunCuration",
                {
                    "scope": self._scope,
                    "mission_data_json": json.dumps(mission_data),
                    "model": model or "",
                },
            )
        else:
            return await self._transport.post(
                "/pipelines/curation",
                {
                    "group_id": self._group_id,
                    "workflow_id": self._workflow_id,
                    "mission_data_json": json.dumps(mission_data),
                    "model": model,
                },
            )

    # =========================================================================
    # Fire-and-Forget Helpers
    # =========================================================================

    def log_event_fire_and_forget(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        context: Optional[str] = None,
    ) -> None:
        """Non-blocking event logging. Errors are logged, not raised."""
        asyncio.create_task(self._safe_call(self.log_event, event_type, event_data, context))

    def update_tool_stats_fire_and_forget(
        self,
        tool_name: str,
        success: bool,
        **kwargs,
    ) -> None:
        """Non-blocking tool stats update."""
        asyncio.create_task(self._safe_call(self.update_tool_stats, tool_name, success, **kwargs))

    def persist_state_fire_and_forget(
        self,
        state_desc: str,
        iteration: int,
        **kwargs,
    ) -> None:
        """Non-blocking state persistence."""
        asyncio.create_task(
            self._safe_call(self.persist_execution_state, state_desc, iteration, **kwargs)
        )

    async def _safe_call(self, fn, *args, **kwargs):
        try:
            await fn(*args, **kwargs)
        except Exception as e:
            logger.warning(f"Fire-and-forget call failed: {e}")

    # =========================================================================
    # Internal
    # =========================================================================

    @property
    def _is_grpc(self) -> bool:
        return self._transport_type == "GrpcTransport"
