"""
MemoryService — the single authoritative domain layer.

Both REST routers and the gRPC adapter call this class.
All storage scoping (group_id) is handled here via copy.copy().
"""

import asyncio
import copy
import json
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class MemoryService:
    """
    Domain service encapsulating all memory operations.

    Injected with storage backends at construction time.
    Uses copy.copy() to create per-call scoped store instances, eliminating
    the _group_id mutation race condition present in direct store access.
    """

    def __init__(
        self,
        episode_store,
        knowledge_store,
        artifact_store,
        ontology_store,
        causal_store=None,
        dragonfly=None,
        short_term=None,
    ):
        self._episode_store = episode_store
        self._knowledge_store = knowledge_store
        self._artifact_store = artifact_store
        self._ontology_store = ontology_store
        self._causal_store = causal_store
        self._dragonfly = dragonfly
        self._short_term = short_term

    # ── Internal scope helpers ────────────────────────────────────────────

    def _ep(self, group_id: str):
        """Return a request-scoped EpisodeStore."""
        s = copy.copy(self._episode_store)
        s._group_id = group_id
        return s

    def _kn(self, group_id: Optional[str]):
        """Return a request-scoped KnowledgeStore. group_id=None → global search."""
        s = copy.copy(self._knowledge_store)
        s._group_id = group_id
        return s

    def _art(self, group_id: str):
        """Return a request-scoped ArtifactStore."""
        s = copy.copy(self._artifact_store)
        s._group_id = group_id
        return s

    # =========================================================================
    # Episodes
    # =========================================================================

    async def store_episode(
        self,
        group_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        episode_type: str = "raw",
    ) -> str:
        return await self._ep(group_id).store_episode(
            content=content,
            metadata=metadata,
            episode_type=episode_type,
        )

    async def search_episodes(
        self,
        group_id: str,
        query: str,
        top_k: int = 25,
        episode_type: Optional[str] = None,
        min_score: float = 0.0,
        expand_adjacent: bool = False,
        expansion_hops: int = 1,
        after_time: Optional[float] = None,
        before_time: Optional[float] = None,
        global_search: bool = False,
    ) -> List[Dict[str, Any]]:
        return await self._ep(group_id).search_episodes(
            query=query,
            top_k=top_k,
            episode_type=episode_type,
            min_score=min_score,
            expand_adjacent=expand_adjacent,
            expansion_hops=expansion_hops,
            after_time=after_time,
            before_time=before_time,
            global_search=global_search,
        )

    async def search_episodes_by_entities(
        self, group_id: str, entity_names: List[str], top_k: int = 10
    ) -> List[Dict[str, Any]]:
        return await self._ep(group_id).search_by_entities(entity_names=entity_names, top_k=top_k)

    async def link_episodes(
        self,
        group_id: str,
        from_uuid: str,
        to_uuid: str,
        edge_type: str = "FOLLOWS",
        properties: Optional[dict] = None,
    ) -> bool:
        return await self._ep(group_id).link_episodes(
            from_uuid=from_uuid,
            to_uuid=to_uuid,
            edge_type=edge_type,
            properties=properties,
        )

    # =========================================================================
    # Knowledge
    # =========================================================================

    async def store_knowledge(
        self,
        group_id: str,
        entries: List[Dict[str, Any]],
        source_mission: str = "",
        mission_status: str = "success",
        source_episode_uuid: str = "",
    ) -> List[str]:
        return await self._kn(group_id).store_knowledge(
            entries=entries,
            source_mission=source_mission,
            mission_status=mission_status,
            source_episode_uuid=source_episode_uuid,
        )

    async def search_knowledge(
        self,
        group_id: Optional[str],
        query: str,
        labels: Optional[List[str]] = None,
        top_k: int = 10,
        min_score: float = 0.0,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        include_embedding: bool = False,
    ) -> List[Dict[str, Any]]:
        # Search knowledge store
        knowledge = await self._kn(group_id).search_hybrid(
            query=query,
            labels=labels,
            top_k=top_k,
            min_score=min_score,
            start_date=start_date,
            end_date=end_date,
            include_embedding=include_embedding,
        )

        # Also search reflection-type episodes globally (metacognition, causal_reflection)
        try:
            ep_store = self._ep(group_id or "default")
            embedding = await ep_store._embed(query)
            refl_result = await ep_store._graph.ro_query(
                """
                MATCH (e:Episode)
                WHERE e.episode_type IN ['metacognition', 'causal_reflection', 'reflection']
                WITH e,
                     (2 - vec.cosineDistance(e.embedding, vecf32($query_vec))) / 2 AS score
                WHERE score >= $min_score
                RETURN e.uuid AS uuid, e.content AS content, e.episode_type AS knowledge_type,
                       e.group_id AS group_id, score
                ORDER BY score DESC
                LIMIT $top_k
                """,
                params={
                    "query_vec": embedding,
                    "min_score": min_score or 0.4,
                    "top_k": max(3, top_k // 3),
                },
            )
            for row in refl_result.result_set:
                knowledge.append(
                    {
                        "uuid": row[0],
                        "content": row[1] or "",
                        "knowledge_type": row[2] or "reflection",
                        "labels": [],
                        "confidence": 0.9,
                        "score": row[4],
                        "source": "reflection_episode",
                    }
                )
        except Exception as e:
            logger.debug(f"Reflection episode search failed: {e}")

        # Sort merged results by score descending, cap to top_k
        knowledge.sort(key=lambda x: x.get("score", 0), reverse=True)
        return knowledge[:top_k]

    async def search_knowledge_by_labels(
        self, group_id: str, labels: List[str], top_k: int = 10
    ) -> List[Dict[str, Any]]:
        return await self._kn(group_id).search_by_labels(labels=labels, top_k=top_k)

    # =========================================================================
    # Artifacts
    # =========================================================================

    async def store_artifacts(
        self,
        group_id: str,
        entries: List[Dict[str, Any]],
        source_mission: str = "",
        mission_status: str = "success",
        source_episode_uuid: str = "",
    ) -> List[str]:
        return await self._art(group_id).store_artifacts(
            entries=entries,
            source_mission=source_mission,
            mission_status=mission_status,
            source_episode_uuid=source_episode_uuid,
        )

    async def search_artifacts(
        self,
        group_id: str,
        query: str,
        labels: Optional[List[str]] = None,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        return await self._art(group_id).search_hybrid(
            query=query,
            labels=labels,
            top_k=top_k,
            min_score=min_score,
        )

    async def get_artifact(self, group_id: str, uuid: str) -> Optional[Dict[str, Any]]:
        return await self._art(group_id).get_by_uuid(uuid)

    async def list_recent_artifacts(self, group_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        return await self._art(group_id).list_recent(limit=limit)

    async def delete_artifact(self, group_id: str, uuid: str) -> bool:
        return await self._art(group_id).delete_by_uuid(uuid)

    # =========================================================================
    # Observe
    # =========================================================================

    async def observe(
        self,
        session_id: str,
        content: str,
        timestamp: Optional[str] = None,
        source: Optional[str] = None,
        metadata: Optional[dict] = None,
        read_only: bool = False,
        summarize: bool = False,
        top_k: int = 10,
        knowledge_top_k: int = 10,
        minimal: bool = False,
        parent_session_id: Optional[str] = None,
    ) -> dict:
        from .observe import observe_core

        return await observe_core(
            episode_store=self._episode_store,
            knowledge_store=self._knowledge_store,
            dragonfly=self._dragonfly,
            ontology_store=self._ontology_store,
            session_id=session_id,
            content=content,
            timestamp=timestamp,
            source=source,
            metadata=dict(metadata or {}),
            read_only=read_only,
            summarize=summarize,
            top_k=top_k,
            knowledge_top_k=knowledge_top_k,
            minimal=minimal,
            causal_store=self._causal_store,
            parent_session_id=parent_session_id,
        )

    # =========================================================================
    # Tool Stats (cross-group, uses dragonfly + short_term directly)
    # =========================================================================

    async def update_tool_stats(
        self,
        tool_name: str,
        success: bool = True,
        duration_ms: float = 0,
        state_description: str = "",
    ) -> None:
        state_hash = str(hash(state_description))[:8] if state_description else "default"
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

    async def get_tool_stats(self) -> dict:
        all_state = await self._dragonfly.hgetall("state")

        tool_stats: Dict[str, dict] = {}
        for key, value in all_state.items():
            if not key.startswith("state:tool_stats:"):
                continue
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
                        "attempts": 0,
                        "successes": 0,
                        "failures": 0,
                        "total_duration_ms": 0,
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

    # =========================================================================
    # Composite Pipelines
    # =========================================================================

    async def startup_pipeline(
        self,
        group_id: Optional[str] = None,
        workflow_id: str = "default",
        task: str = "",
        model: Optional[str] = None,
        parent_session_id: Optional[str] = None,
    ) -> dict:
        """
        Full startup pipeline — replaces 7-step startup sequence.

        group_id is optional. When omitted, a UUID session_id is auto-generated
        and returned in the response so callers can use it for subsequent observe calls.

        Steps:
          0. Reinterpret task (DSPy) → search labels + optimized query
          1. Episode vector search → raw results string
          2. Knowledge + Artifact hybrid search (parallel)
          3. LLM filter on episode results
          4. Tool stats from DragonflyDB
          5. Infer initial state
          6. Synthesize background narrative
        """
        session_id = group_id or str(uuid4())
        ep_store = self._ep(session_id)
        kn_store = self._kn(session_id)
        art_store = self._art(session_id)

        # Persist session node + parent link (idempotent MERGE)
        asyncio.create_task(ep_store.ensure_session(session_id, parent_session_id))

        # Step 1: Task reinterpretation
        search_labels: List[str] = []
        search_query = task
        try:
            from ..intelligence.evaluation.reinterpret import reinterpret_task

            reinterpretation = await reinterpret_task(task=task, model=model)
            search_labels = reinterpretation.get("search_labels", [])
            search_query = reinterpretation.get("search_query", task)
            logger.info(
                f"Task reinterpreted: {len(search_labels)} labels, "
                f"complexity={reinterpretation.get('complexity_assessment', '?')}"
            )
        except Exception as e:
            logger.warning(f"Task reinterpretation failed (non-critical): {e}")

        # Step 1: Episode vector search — GLOBAL (cross-session)
        long_term_context = ""
        try:
            results = await ep_store.search_episodes(
                query=search_query,
                top_k=10,
                min_score=0.55,
                global_search=True,  # search across ALL sessions
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
        async def _search_knowledge():
            try:
                results = await kn_store.search_hybrid(
                    query=search_query,
                    labels=search_labels,
                    top_k=10,
                    min_score=0.40,
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
                results = await art_store.search_hybrid(
                    query=search_query,
                    labels=search_labels,
                    top_k=8,
                    min_score=0.45,
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

        async def _search_reflections():
            """Search metacognition, causal_reflection, and reflection episodes globally."""
            try:
                embedding = await ep_store._embed(search_query)
                result = await ep_store._graph.ro_query(
                    """
                    MATCH (e:Episode)
                    WHERE e.episode_type IN ['metacognition', 'causal_reflection', 'reflection']
                    WITH e,
                         (2 - vec.cosineDistance(e.embedding, vecf32($query_vec))) / 2 AS score
                    WHERE score >= 0.45
                    RETURN e.uuid AS uuid, e.content AS content, e.episode_type AS episode_type,
                           e.group_id AS group_id, score
                    ORDER BY score DESC
                    LIMIT 5
                    """,
                    params={"query_vec": embedding},
                )
                if not result.result_set:
                    return ""
                lines = ["## Prior Reflections & Metacognition"]
                for i, r in enumerate(result.result_set, 1):
                    etype = r[2] or "reflection"
                    content = (r[1] or "")[:300]
                    score = r[4]
                    lines.append(f"{i}. [{etype}] {content}... (score={score:.2f})")
                return "\n".join(lines)
            except Exception as e:
                logger.warning(f"Reflections search failed (non-critical): {e}")
                return ""

        knowledge_context, artifacts_context, reflections_context = await asyncio.gather(
            _search_knowledge(),
            _search_artifacts(),
            _search_reflections(),
        )

        # Step 3: LLM filter on episode results
        if long_term_context:
            try:
                from ..intelligence.evaluation.filter import filter_memory_results

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
            stats_result = await self.get_tool_stats()
            tool_stats_context = stats_result.get("formatted_stats", "")
        except Exception as e:
            logger.warning(f"Tool stats failed (non-critical): {e}")

        # Step 5: Infer state
        inferred_state = ""
        try:
            from ..intelligence.evaluation.infer_state import infer_state

            inferred_state = await infer_state(
                task=task,
                retrieved_memories=long_term_context,
                model=model,
            )
        except Exception as e:
            logger.warning(f"State inference failed (non-critical): {e}")

        # Step 6: Synthesize background narrative
        background_narrative = ""
        try:
            from ..intelligence.synthesis.synthesize import synthesize_background

            # Combine knowledge + reflections into a single context block
            combined_knowledge = knowledge_context
            if reflections_context:
                combined_knowledge = (
                    (combined_knowledge + "\n\n" + reflections_context)
                    if combined_knowledge
                    else reflections_context
                )

            result = await synthesize_background(
                task=task,
                long_term_context=long_term_context,
                tool_stats_context=tool_stats_context,
                inferred_state=inferred_state,
                model=model,
                knowledge_context=combined_knowledge,
                artifacts_context=artifacts_context,
                episode_store=ep_store,
            )
            background_narrative = result.get("narrative", "")
        except Exception as e:
            logger.warning(f"Background synthesis failed (non-critical): {e}")

        return {
            "session_id": session_id,
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

    async def run_curation(
        self,
        group_id: str,
        workflow_id: str = "default",
        mission_data: Optional[Dict[str, Any]] = None,
        source_episode_uuids: Optional[List[str]] = None,
        model: Optional[str] = None,
    ) -> dict:
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
        ep_store = self._ep(group_id)
        kn_store = self._kn(group_id)
        art_store = self._art(group_id)

        if mission_data is None:
            mission_data = {}
        task = mission_data.get("task", "")
        status = mission_data.get("status", "")
        run_id = mission_data.get("run_id", "")

        # Step 1: Generate reflection sections (returns dict with separate parts)
        reflection_sections = {}
        try:
            from ..intelligence.synthesis.reflect import generate_reflection

            reflection_sections = await generate_reflection(
                mission_data, model=model, group_id=group_id
            )
            logger.info(
                "Generated reflection sections: %s",
                {k: len(v) for k, v in reflection_sections.items() if v},
            )
        except Exception as e:
            logger.warning(f"Reflection generation failed (non-critical): {e}")
            reflection_sections = {"reflection": f"Mission completed with status={status}."}

        # Backward compat: combined reflection text for knowledge extraction
        reflection = reflection_sections.get("reflection", "")

        # Step 2: Store each reflection section as a separate typed episode
        reflection_uuid = ""
        section_uuids = {}
        for section_type, content_text in reflection_sections.items():
            if not content_text:
                continue
            try:
                ep_uuid = await ep_store.store_episode(
                    content=f"{section_type.replace('_', ' ').title()} for: {task[:200]}\n\n{content_text}",
                    metadata={
                        "source": "curator",
                        "task": task[:200],
                        "status": status,
                        "reflection_type": section_type,
                    },
                    episode_type=section_type,
                )
                section_uuids[section_type] = ep_uuid
                if section_type == "reflection":
                    reflection_uuid = ep_uuid
                logger.info(f"Stored {section_type} episode: {ep_uuid}")
            except Exception as e:
                logger.warning(f"Failed to store {section_type} (non-critical): {e}")

        # Use first UUID as reflection_uuid if main reflection failed
        if not reflection_uuid and section_uuids:
            reflection_uuid = next(iter(section_uuids.values()))

        # Step 2b: Link reflection to source raw episodes (if provided)
        if source_episode_uuids and reflection_uuid:
            for src_uuid in source_episode_uuids:
                try:
                    await ep_store._graph.query(
                        """MATCH (r:Episode {uuid: $r_uuid})
                           MATCH (s:Episode {uuid: $s_uuid})
                           CREATE (r)-[:DERIVED_FROM]->(s)""",
                        params={"r_uuid": reflection_uuid, "s_uuid": src_uuid},
                    )
                except Exception:
                    pass

        # Step 3: Extract knowledge entries
        knowledge_entries: List[dict] = []
        try:
            from ..intelligence.extract.knowledge import extract_knowledge

            data_source_type = mission_data.get("data_source_type", "mission")
            knowledge_entries = await extract_knowledge(
                mission_data=mission_data,
                reflection=reflection,
                model=model,
                data_source_type=data_source_type,
            )
            logger.info(f"Extracted {len(knowledge_entries)} knowledge entries")
        except Exception as e:
            logger.warning(f"Knowledge extraction failed (non-critical): {e}")

        # Step 4: Store knowledge
        knowledge_count = 0
        if knowledge_entries:
            try:
                uuids = await kn_store.store_knowledge(
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
        artifact_entries: List[dict] = []
        try:
            from ..intelligence.extract.artifacts import extract_artifacts

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
                uuids = await art_store.store_artifacts(
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
            from ..intelligence.synthesis.compress import compress_events

            state = mission_data.get("state", {})
            state_desc = state.get("state_description", "") if isinstance(state, dict) else ""
            result = await compress_events(
                short_term_memory=self._short_term,
                episode_store=ep_store,
                run_id=run_id,
                state_description=state_desc,
                model=model,
            )
            events_compressed = result.get("compressed", False)
        except Exception as e:
            logger.warning(f"Event compression failed (non-critical): {e}")

        # Step 7b: Extract and store causal claims
        causal_count = 0
        causal_source = mission_data.get("output", "")
        if self._causal_store and causal_source:
            try:
                from ..intelligence.extract.causals import extract_causal_claims

                causal_claims = await extract_causal_claims(causal_source)
                for claim in causal_claims:
                    try:
                        await self._causal_store.upsert_claim(
                            cause_summary=claim["cause"],
                            effect_summary=claim["effect"],
                            mechanism=claim.get("mechanism", ""),
                            confidence=claim.get("confidence", 0.8),
                            causal_type=claim.get("causal_type", "causes"),
                            cause_entity=claim.get("cause_norm"),
                            effect_entity=claim.get("effect_norm"),
                            group_id=group_id,
                        )
                        causal_count += 1
                    except Exception:
                        pass
                if causal_count:
                    # Auto-link knowledge as SUPPORTS evidence for causal claims
                    if knowledge_entries:
                        try:
                            claims = await self._causal_store.list_claims(
                                group_id=group_id, limit=50
                            )
                            for claim in claims:
                                claim_text = f"{claim.get('cause_summary', '')} {claim.get('effect_summary', '')}"
                                await self._causal_store._embed(claim_text)
                                # Find knowledge that semantically matches this claim
                                matches = await kn_store.search_hybrid(
                                    query=claim_text,
                                    top_k=3,
                                    min_score=0.6,
                                )
                                for kn in matches:
                                    kn_uuid = kn.get("uuid", "")
                                    if kn_uuid:
                                        await self._causal_store.add_evidence(
                                            claim["uuid"],
                                            kn_uuid,
                                            "supports",
                                            weight=kn.get("score", 0.7),
                                        )
                        except Exception as e:
                            logger.debug(f"Auto-linking knowledge to causal claims: {e}")

                    await self._causal_store.revise_beliefs(group_id)
                    await self._causal_store.auto_chain(group_id)
                    logger.info(f"Stored {causal_count} causal claims")

                    # Store causal reflection as a separate episode
                    causal_lines = []
                    for claim in causal_claims:
                        line = f"- {claim['cause']} → {claim['effect']}"
                        if claim.get("mechanism"):
                            line += f" ({claim['mechanism'][:100]})"
                        line += f" [confidence={claim.get('confidence', 0.8):.2f}]"
                        causal_lines.append(line)
                    causal_summary = (
                        f"Causal beliefs extracted ({causal_count} claims):\n"
                        + "\n".join(causal_lines)
                    )
                    try:
                        await ep_store.store_episode(
                            content=f"Causal Reflection for: {task[:200]}\n\n{causal_summary}",
                            metadata={
                                "source": "curator",
                                "task": task[:200],
                                "reflection_type": "causal_reflection",
                                "causal_count": causal_count,
                            },
                            episode_type="causal_reflection",
                        )
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Causal extraction failed (non-critical): {e}")

        return {
            "reflection": reflection,
            "reflection_uuid": reflection_uuid,
            "section_uuids": section_uuids,
            "knowledge_count": knowledge_count,
            "artifact_count": artifact_count,
            "causal_count": causal_count,
            "events_compressed": events_compressed,
        }
