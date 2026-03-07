"""
Service handler — implements all gRPC method logic.

This is the shared business logic layer that both gRPC and REST call into.
Storage classes are injected at construction time.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryServiceHandler:
    """
    Implements all memory service operations.

    Injected with storage backends at construction time.
    Both gRPC servicer and REST routers can delegate to this handler.
    """

    def __init__(
        self,
        dragonfly,       # DragonflyClient
        short_term,      # ShortTermMemory
        episode_store,   # EpisodeStore
        knowledge_store, # KnowledgeStore
        artifact_store,  # ArtifactStore
    ):
        self._dragonfly = dragonfly
        self._short_term = short_term
        self._episode_store = episode_store
        self._knowledge_store = knowledge_store
        self._artifact_store = artifact_store

    def _apply_scope(self, req: dict, *stores) -> tuple:
        """Extract scope from request and apply to dragonfly + stores.

        Returns (group_id, workflow_id).
        """
        scope = req.get("scope", {})
        group_id = scope.get("group_id", "default")
        workflow_id = scope.get("workflow_id", "default")
        self._dragonfly.set_scope(group_id=group_id, workflow_id=workflow_id)
        for store in stores:
            store._group_id = group_id
        return group_id, workflow_id

    # =========================================================================
    # Events
    # =========================================================================

    async def log_event(self, req: dict) -> dict:
        self._apply_scope(req)
        data = req.get("event_data_json", "{}")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {"raw": data}

        event_id = await self._dragonfly.log_event(
            req.get("event_type", "observation"),
            data,
        )
        return {"event_id": event_id or ""}

    async def get_recent_events(self, req: dict) -> dict:
        self._apply_scope(req)
        events = await self._dragonfly.get_recent_events(
            count=req.get("count", 10),
            event_type=req.get("event_type_filter") or None,
        )
        return {"events": events}

    async def search_events(self, req: dict) -> dict:
        self._apply_scope(req)
        event_types = req.get("event_types", [])
        limit = req.get("limit", 50)
        events = await self._dragonfly.get_recent_events(count=limit)
        if event_types:
            events = [e for e in events if e.get("type") in event_types]
        return {"events": events}

    # =========================================================================
    # Episodes
    # =========================================================================

    async def store_episode(self, req: dict) -> dict:
        self._apply_scope(req, self._episode_store)
        metadata = req.get("metadata_json")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = None

        uuid = await self._episode_store.store_episode(
            content=req.get("content", ""),
            metadata=metadata,
            episode_type=req.get("episode_type", "raw"),
        )
        return {"uuid": uuid}

    async def search_episodes(self, req: dict) -> dict:
        self._apply_scope(req, self._episode_store)
        results = await self._episode_store.search_episodes(
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
        self._apply_scope(req, self._episode_store)
        success = await self._episode_store.link_episodes(
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
        self._apply_scope(req, self._knowledge_store)
        entries = req.get("entries", [])
        uuids = await self._knowledge_store.store_knowledge(
            entries=entries,
            source_mission=req.get("source_mission", ""),
            mission_status=req.get("mission_status", "success"),
            source_episode_uuid=req.get("source_episode_uuid", ""),
        )
        return {"uuids": uuids}

    async def search_knowledge(self, req: dict) -> dict:
        self._apply_scope(req, self._knowledge_store)
        results = await self._knowledge_store.search_hybrid(
            query=req.get("query", ""),
            labels=req.get("labels") or None,
            top_k=req.get("top_k", 10),
            min_score=req.get("min_score", 0.50),
        )
        return {"entries": results}

    async def search_by_labels(self, req: dict) -> dict:
        self._apply_scope(req, self._knowledge_store)
        results = await self._knowledge_store.search_by_labels(
            labels=req.get("labels", []),
            top_k=req.get("top_k", 10),
        )
        return {"entries": results}

    # =========================================================================
    # Artifacts
    # =========================================================================

    async def store_artifacts(self, req: dict) -> dict:
        self._apply_scope(req, self._artifact_store)
        entries = req.get("entries", [])
        uuids = await self._artifact_store.store_artifacts(
            entries=entries,
            source_mission=req.get("source_mission", ""),
            mission_status=req.get("mission_status", "success"),
            source_episode_uuid=req.get("source_episode_uuid", ""),
        )
        return {"uuids": uuids}

    async def search_artifacts(self, req: dict) -> dict:
        self._apply_scope(req, self._artifact_store)
        results = await self._artifact_store.search_hybrid(
            query=req.get("query", ""),
            labels=req.get("labels") or None,
            top_k=req.get("top_k", 10),
            min_score=req.get("min_score", 0.45),
        )
        return {"entries": results}

    async def get_artifact(self, req: dict) -> dict:
        self._apply_scope(req, self._artifact_store)
        result = await self._artifact_store.get_by_uuid(req.get("uuid", ""))
        return {"artifact": result, "found": result is not None}

    async def list_recent_artifacts(self, req: dict) -> dict:
        self._apply_scope(req, self._artifact_store)
        results = await self._artifact_store.list_recent(
            limit=req.get("limit", 50),
        )
        return {"entries": results}

    async def delete_artifact(self, req: dict) -> dict:
        self._apply_scope(req, self._artifact_store)
        existed = await self._artifact_store.delete_by_uuid(req.get("uuid", ""))
        return {"existed": existed}

    # =========================================================================
    # State
    # =========================================================================

    async def persist_execution_state(self, req: dict) -> dict:
        group_id, workflow_id = self._apply_scope(req)
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

        await self._dragonfly.hset(state_key, mapping)
        return {"success": True}

    async def get_execution_state(self, req: dict) -> dict:
        group_id, workflow_id = self._apply_scope(req)
        state_key = f"exec_state:{group_id}:{workflow_id}"

        data = await self._dragonfly.hgetall(state_key)
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
        scope = req.get("scope", {})
        tool_name = req.get("tool_name", "")
        success = req.get("success", True)
        duration_ms = req.get("duration_ms", 0)
        state_desc = req.get("state_description", "")

        state_hash = str(hash(state_desc))[:8] if state_desc else "default"
        stats_key = f"state:tool_stats:{tool_name}:{state_hash}"

        existing = await self._short_term.get(stats_key)
        if existing and isinstance(existing, dict):
            existing["attempts"] = existing.get("attempts", 0) + 1
            if success:
                existing["successes"] = existing.get("successes", 0) + 1
            else:
                existing["failures"] = existing.get("failures", 0) + 1
            existing["total_duration_ms"] = existing.get("total_duration_ms", 0) + duration_ms
            stats = existing
        else:
            stats = {
                "tool_name": tool_name,
                "attempts": 1,
                "successes": 1 if success else 0,
                "failures": 0 if success else 1,
                "total_duration_ms": duration_ms,
            }

        await self._short_term.save(stats_key, stats)
        return {"success": True}

    async def get_tool_stats(self, req: dict) -> dict:
        all_state = await self._dragonfly.hgetall("state")

        tool_stats = {}
        for key, value in all_state.items():
            if key.startswith("state:tool_stats:"):
                parts = key.split(":")
                tool_name = parts[2] if len(parts) > 2 else "unknown"
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except Exception:
                        continue
                if isinstance(value, dict):
                    stat_data = value.get("value", value)
                    if isinstance(stat_data, str):
                        try:
                            stat_data = json.loads(stat_data)
                        except Exception:
                            continue
                    if tool_name not in tool_stats:
                        tool_stats[tool_name] = {
                            "attempts": 0, "successes": 0,
                            "failures": 0, "total_duration_ms": 0,
                        }
                    for field in ("attempts", "successes", "failures", "total_duration_ms"):
                        tool_stats[tool_name][field] += stat_data.get(field, 0)

        lines = []
        for tool, stats in sorted(tool_stats.items()):
            attempts = stats["attempts"]
            successes = stats["successes"]
            avg_ms = stats["total_duration_ms"] // max(attempts, 1)
            lines.append(f"  {tool}: {attempts} calls, {successes} ok, avg {avg_ms}ms")

        formatted = "\n".join(lines) if lines else "No tool stats available."
        return {
            "formatted_stats": formatted,
            "raw_stats_json": json.dumps(tool_stats),
        }

    async def get_memory_context(self, req: dict) -> dict:
        self._apply_scope(req)
        event_limit = req.get("event_limit", 5)
        events = await self._dragonfly.get_recent_events(count=event_limit)

        lines = []
        for e in reversed(events):
            etype = e.get("type", "")
            data = e.get("data", {})
            content = data.get("content", str(data)[:200]) if isinstance(data, dict) else str(data)[:200]
            lines.append(f"[{etype}] {content}")

        formatted = "\n".join(lines) if lines else "No recent events."
        return {"formatted_context": formatted}

    # =========================================================================
    # Smart Operations (LLM-powered)
    # =========================================================================

    async def reinterpret_task(self, req: dict) -> dict:
        from ..smart.reinterpret import reinterpret_task
        result = await reinterpret_task(
            task=req.get("task", ""),
            model=req.get("model") or None,
        )
        return {
            "search_labels": result.get("search_labels", []),
            "search_query": result.get("search_query", ""),
            "complexity": result.get("complexity_assessment", ""),
        }

    async def filter_memory(self, req: dict) -> dict:
        from ..smart.filter import filter_memory_results
        result = await filter_memory_results(
            task=req.get("task", ""),
            search_results=req.get("search_results", ""),
            model=req.get("model") or None,
            max_results=req.get("max_results", 5),
        )
        return {"filtered_results": result}

    async def infer_state_op(self, req: dict) -> dict:
        from ..smart.infer_state import infer_state
        result = await infer_state(
            task=req.get("task", ""),
            retrieved_memories=req.get("retrieved_memories", ""),
            model=req.get("model") or None,
        )
        return {"state_description": result}

    async def synthesize_background_op(self, req: dict) -> dict:
        from ..smart.synthesize import synthesize_background
        self._apply_scope(req, self._episode_store)
        result = await synthesize_background(
            task=req.get("task", ""),
            long_term_context=req.get("long_term_context", ""),
            tool_stats_context=req.get("tool_stats_context", ""),
            inferred_state=req.get("state_description", ""),
            model=req.get("model") or None,
            knowledge_context=req.get("knowledge_context", ""),
            artifacts_context=req.get("artifacts_context", ""),
            episode_store=self._episode_store,
        )
        return result

    async def generate_reflection_op(self, req: dict) -> dict:
        from ..smart.reflect import generate_reflection
        mission_data = req.get("mission_data_json", "{}")
        if isinstance(mission_data, str):
            mission_data = json.loads(mission_data)
        result = await generate_reflection(mission_data)
        return {"reflection": result}

    async def extract_knowledge_op(self, req: dict) -> dict:
        from ..smart.extract_knowledge import extract_knowledge
        mission_data = req.get("mission_data_json", "{}")
        if isinstance(mission_data, str):
            mission_data = json.loads(mission_data)
        entries = await extract_knowledge(
            mission_data=mission_data,
            reflection=req.get("reflection", ""),
            model=req.get("model") or None,
        )
        return {"entries_json": json.dumps(entries)}

    async def extract_artifacts_op(self, req: dict) -> dict:
        from ..smart.extract_artifacts import extract_artifacts
        mission_data = req.get("mission_data_json", "{}")
        if isinstance(mission_data, str):
            mission_data = json.loads(mission_data)
        entries = await extract_artifacts(
            mission_data=mission_data,
            model=req.get("model") or None,
        )
        return {"entries_json": json.dumps(entries)}

    async def compress_events_op(self, req: dict) -> dict:
        from ..smart.compress import compress_events
        self._apply_scope(req)
        result = await compress_events(
            short_term_memory=self._short_term,
            episode_store=self._episode_store,
            run_id=req.get("run_id", ""),
            state_description=req.get("state_description", ""),
            model=req.get("model") or None,
        )
        return result

    # =========================================================================
    # Observe (single-endpoint memory interface)
    # =========================================================================

    async def observe(self, req: dict) -> dict:
        """
        Observe endpoint — delegates to core observe logic.

        Uses the short-term first architecture: DragonflyDB session as primary,
        with background FalkorDB hydration.
        """
        from ..core.observe import observe_core

        return await observe_core(
            episode_store=self._episode_store,
            knowledge_store=self._knowledge_store,
            dragonfly=self._dragonfly,
            session_id=req.get("session_id", "default"),
            content=req.get("content", ""),
            timestamp=req.get("timestamp"),
            source=req.get("source", ""),
            metadata=dict(req.get("metadata") or {}),
        )

    # =========================================================================
    # Pipelines (composite operations — reduce round trips)
    # =========================================================================

    async def startup_pipeline(self, req: dict) -> dict:
        """
        Full startup pipeline — replaces 7-step startup sequence.

        Steps:
          0. Reinterpret task (DSPy) → search labels + optimized query
          1. Episode vector search → raw results string
          2. Knowledge + Artifact hybrid search (parallel)
          3. LLM filter on episode results
          4. Tool stats from DragonflyDB
          5. Infer initial state
          6. Synthesize background narrative
        """
        import asyncio

        self._apply_scope(
            req, self._episode_store, self._knowledge_store, self._artifact_store,
        )
        task = req.get("task", "")
        model = req.get("model") or None

        # Step 0: Task reinterpretation
        search_labels = []
        search_query = task
        try:
            from ..smart.reinterpret import reinterpret_task
            reinterpretation = await reinterpret_task(task=task, model=model)
            search_labels = reinterpretation.get("search_labels", [])
            search_query = reinterpretation.get("search_query", task)
            logger.info(
                f"Task reinterpreted: {len(search_labels)} labels, "
                f"complexity={reinterpretation.get('complexity_assessment', '?')}"
            )
        except Exception as e:
            logger.warning(f"Task reinterpretation failed (non-critical): {e}")

        # Step 1: Episode vector search
        long_term_context = ""
        try:
            results = await self._episode_store.search_episodes(
                query=search_query, top_k=10, min_score=0.55,
            )
            if results:
                lines = ["## Related Memory (Episode Search)"]
                for i, r in enumerate(results[:10], 1):
                    content = str(r.get("content", ""))[:200]
                    score = r.get("score", 0)
                    etype = r.get("episode_type", "raw")
                    lines.append(f"{i}. [{etype}] {content}... (score={score:.2f})")
                long_term_context = "\n".join(lines)
        except Exception as e:
            logger.warning(f"Episode search failed (non-critical): {e}")

        # Step 2: Knowledge + Artifact search (parallel)
        knowledge_context = ""
        artifacts_context = ""

        async def _search_knowledge():
            try:
                results = await self._knowledge_store.search_hybrid(
                    query=search_query, labels=search_labels, top_k=10, min_score=0.40,
                )
                if not results:
                    return ""
                lines = ["## Accumulated Knowledge"]
                for i, r in enumerate(results, 1):
                    ktype = r.get("knowledge_type", "fact")
                    content = r.get("content", "")[:200]
                    labels_val = r.get("labels", [])
                    if isinstance(labels_val, str):
                        try:
                            labels_val = json.loads(labels_val)
                        except Exception:
                            labels_val = []
                    label_str = ", ".join(labels_val[:3]) if labels_val else ""
                    score = r.get("score", 0)
                    lines.append(
                        f"{i}. [{ktype}] {content}"
                        + (f" (labels: {label_str})" if label_str else "")
                        + f" ({score:.2f})"
                    )
                return "\n".join(lines)
            except Exception as e:
                logger.warning(f"Knowledge search failed (non-critical): {e}")
                return ""

        async def _search_artifacts():
            try:
                results = await self._artifact_store.search_hybrid(
                    query=search_query, labels=search_labels, top_k=8, min_score=0.45,
                )
                if not results:
                    return ""
                lines = ["## Known Artifacts"]
                for i, r in enumerate(results, 1):
                    name = r.get("name", "unknown")
                    atype = r.get("artifact_type", "file")
                    path = r.get("path", "")
                    desc = r.get("description", "")[:150]
                    labels_val = r.get("labels", [])
                    if isinstance(labels_val, str):
                        try:
                            labels_val = json.loads(labels_val)
                        except Exception:
                            labels_val = []
                    label_str = ", ".join(labels_val[:3]) if labels_val else ""
                    score = r.get("score", 0)
                    source = r.get("source_mission", "")[:60]
                    lines.append(
                        f"{i}. **{name}** [{atype}] — {desc}"
                        + (f"\n   Path: {path}" if path else "")
                        + (f"\n   Labels: {label_str}" if label_str else "")
                        + f"\n   Source: {source} ({score:.2f})"
                    )
                return "\n".join(lines)
            except Exception as e:
                logger.warning(f"Artifact search failed (non-critical): {e}")
                return ""

        knowledge_context, artifacts_context = await asyncio.gather(
            _search_knowledge(), _search_artifacts(),
        )

        # Step 3: LLM filter on episode results
        if long_term_context:
            try:
                from ..smart.filter import filter_memory_results
                long_term_context = await filter_memory_results(
                    task=task,
                    search_results=long_term_context,
                    model=model,
                    max_results=5,
                )
            except Exception as e:
                logger.warning(f"Memory filter failed (non-critical): {e}")
                long_term_context = ""

        # Step 4: Tool stats
        tool_stats_context = ""
        try:
            stats_result = await self.get_tool_stats({})
            tool_stats_context = stats_result.get("formatted_stats", "")
        except Exception as e:
            logger.warning(f"Tool stats failed (non-critical): {e}")

        # Step 5: Infer state
        inferred_state = ""
        try:
            from ..smart.infer_state import infer_state
            inferred_state = await infer_state(
                task=task, retrieved_memories=long_term_context, model=model,
            )
        except Exception as e:
            logger.warning(f"State inference failed (non-critical): {e}")

        # Step 6: Synthesize background narrative
        background_narrative = ""
        try:
            from ..smart.synthesize import synthesize_background
            result = await synthesize_background(
                task=task,
                long_term_context=long_term_context,
                tool_stats_context=tool_stats_context,
                inferred_state=inferred_state,
                model=model,
                knowledge_context=knowledge_context,
                artifacts_context=artifacts_context,
                episode_store=self._episode_store,
            )
            background_narrative = result.get("narrative", "")
        except Exception as e:
            logger.warning(f"Background synthesis failed (non-critical): {e}")

        return {
            "background_narrative": background_narrative,
            "inferred_state": inferred_state,
            "long_term_context": long_term_context,
            "knowledge_context": knowledge_context,
            "artifacts_context": artifacts_context,
            "tool_stats_context": tool_stats_context,
            "search_labels": search_labels,
            "search_query": search_query,
            "complexity": "",
        }

    async def run_curation(self, req: dict) -> dict:
        """
        Full curation pipeline — replaces 7-step CuratorWorkflow.

        Steps:
          1. Generate reflection from mission data
          2. Store reflection as episode
          3. Extract knowledge entries
          4. Store knowledge in graph
          5. Extract artifact entries
          6. Store artifacts in graph
          7. Compress old raw events
        """
        self._apply_scope(
            req, self._episode_store, self._knowledge_store, self._artifact_store,
        )
        model = req.get("model") or None

        mission_data_json = req.get("mission_data_json", "{}")
        if isinstance(mission_data_json, str):
            mission_data = json.loads(mission_data_json)
        else:
            mission_data = mission_data_json

        task = mission_data.get("task", "")
        status = mission_data.get("status", "")
        run_id = mission_data.get("run_id", "")

        # Step 1: Generate reflection
        reflection = ""
        try:
            from ..smart.reflect import generate_reflection
            reflection = await generate_reflection(mission_data, model=model)
            logger.info(f"Generated reflection: {len(reflection)} chars")
        except Exception as e:
            logger.warning(f"Reflection generation failed (non-critical): {e}")
            reflection = f"Mission completed with status={status}."

        # Step 2: Store reflection as episode
        reflection_uuid = ""
        try:
            reflection_uuid = await self._episode_store.store_episode(
                content=f"Reflection for: {task[:200]}\n\n{reflection}",
                metadata={"source": "curator", "task": task[:200], "status": status},
                episode_type="reflection",
            )
            logger.info(f"Stored reflection episode: {reflection_uuid}")
        except Exception as e:
            logger.warning(f"Failed to store reflection (non-critical): {e}")

        # Step 2b: Link reflection to source raw episodes (if provided)
        source_uuids = req.get("source_episode_uuids", [])
        if source_uuids and reflection_uuid:
            for src_uuid in source_uuids:
                try:
                    await self._episode_store._graph.query(
                        """MATCH (r:Episode {uuid: $r_uuid})
                           MATCH (s:Episode {uuid: $s_uuid})
                           CREATE (r)-[:DERIVED_FROM]->(s)""",
                        params={"r_uuid": reflection_uuid, "s_uuid": src_uuid},
                    )
                except Exception:
                    pass

        # Step 2c: Extract and link entities
        try:
            from ..smart.extract_entities import extract_entities
            mission_content = f"{task}\n\n{reflection}"
            entities = await extract_entities(content=mission_content, model=model)
            if entities:
                # Link to reflection episode
                if reflection_uuid:
                    await self._episode_store.link_entities(reflection_uuid, entities)
                # Link to source raw episodes
                for src_uuid in source_uuids:
                    await self._episode_store.link_entities(src_uuid, entities)
                logger.info(f"Linked {len(entities)} entities to episodes")
        except Exception as e:
            logger.warning(f"Entity extraction failed (non-critical): {e}")

        # Step 3: Extract knowledge entries
        knowledge_entries = []
        try:
            from ..smart.extract_knowledge import extract_knowledge
            knowledge_entries = await extract_knowledge(
                mission_data=mission_data,
                reflection=reflection,
                model=model,
            )
            logger.info(f"Extracted {len(knowledge_entries)} knowledge entries")
        except Exception as e:
            logger.warning(f"Knowledge extraction failed (non-critical): {e}")

        # Step 4: Store knowledge
        knowledge_count = 0
        if knowledge_entries:
            try:
                uuids = await self._knowledge_store.store_knowledge(
                    entries=knowledge_entries,
                    source_mission=task[:200],
                    mission_status=status,
                    source_episode_uuid=reflection_uuid,
                )
                knowledge_count = len(uuids)
                logger.info(f"Stored {knowledge_count} knowledge entries")
            except Exception as e:
                logger.warning(f"Failed to store knowledge (non-critical): {e}")

        # Step 5: Extract artifact entries
        artifact_entries = []
        try:
            from ..smart.extract_artifacts import extract_artifacts
            artifact_entries = await extract_artifacts(
                mission_data=mission_data,
                model=model,
            )
            logger.info(f"Extracted {len(artifact_entries)} artifact entries")
        except Exception as e:
            logger.warning(f"Artifact extraction failed (non-critical): {e}")

        # Step 6: Store artifacts
        artifact_count = 0
        if artifact_entries:
            try:
                uuids = await self._artifact_store.store_artifacts(
                    entries=artifact_entries,
                    source_mission=task[:200],
                    mission_status=status,
                    source_episode_uuid=reflection_uuid,
                )
                artifact_count = len(uuids)
                logger.info(f"Stored {artifact_count} artifact entries")
            except Exception as e:
                logger.warning(f"Failed to store artifacts (non-critical): {e}")

        # Step 7: Compress old events
        events_compressed = False
        try:
            from ..smart.compress import compress_events
            state = mission_data.get("state", {})
            state_desc = state.get("state_description", "") if isinstance(state, dict) else ""
            result = await compress_events(
                short_term_memory=self._short_term,
                episode_store=self._episode_store,
                run_id=run_id,
                state_description=state_desc,
                model=model,
            )
            events_compressed = result.get("compressed", False)
        except Exception as e:
            logger.warning(f"Event compression failed (non-critical): {e}")

        return {
            "reflection": reflection,
            "reflection_uuid": reflection_uuid,
            "knowledge_count": knowledge_count,
            "artifact_count": artifact_count,
            "events_compressed": events_compressed,
        }
