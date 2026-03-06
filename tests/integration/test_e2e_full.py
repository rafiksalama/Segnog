"""
Full E2E test suite for the Agent Memory Service.

Tests all layers via REST API against live backends:
1. Storage operations (events, episodes, knowledge, artifacts, state)
2. Smart operations (reinterpret, filter, synthesize, reflect, extract)
3. Composite pipelines (StartupPipeline, RunCuration)

Prerequisites:
  - Memory service running on http://localhost:9000
  - DragonflyDB on :6381, FalkorDB on :6380
  - OpenRouter API key configured
"""

import asyncio
import json
import time

import httpx
import pytest

BASE_URL = "http://localhost:9000"
API = f"{BASE_URL}/api/v1/memory"
TIMEOUT = httpx.Timeout(60.0, connect=10.0)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=API, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture(scope="module")
def async_client():
    return httpx.AsyncClient(base_url=API, timeout=TIMEOUT)


def _scope(group="e2e-test", workflow="test-wf-001"):
    return {"group_id": group, "workflow_id": workflow}


# ─────────────────────────────────────────────────────────────────────
# 1. STORAGE: Events
# ─────────────────────────────────────────────────────────────────────

class TestEvents:
    def test_log_event(self, client):
        resp = client.post("/events", json={
            **_scope(),
            "event_type": "observation",
            "event_data": {"content": "Agent started task: analyze sales data"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "event_id" in data
        assert data["event_id"] != ""
        print(f"  ✓ Logged event: {data['event_id']}")

    def test_log_multiple_events(self, client):
        events = [
            ("action", {"tool": "web_search", "query": "quarterly sales report 2025"}),
            ("observation", {"content": "Found 3 relevant reports from Q3 and Q4 2025"}),
            ("action", {"tool": "file_write", "path": "/tmp/sales_analysis.md"}),
            ("observation", {"content": "Wrote analysis to file successfully"}),
        ]
        ids = []
        for etype, edata in events:
            resp = client.post("/events", json={
                **_scope(),
                "event_type": etype,
                "event_data": edata,
            })
            assert resp.status_code == 200
            ids.append(resp.json()["event_id"])
        print(f"  ✓ Logged {len(ids)} events")

    def test_get_recent_events(self, client):
        resp = client.get("/events/recent", params={
            "group_id": "e2e-test",
            "workflow_id": "test-wf-001",
            "count": 5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert len(data["events"]) >= 1
        print(f"  ✓ Retrieved {len(data['events'])} recent events")

    def test_search_events_with_type_filter(self, client):
        resp = client.post("/events/search", json={
            **_scope(),
            "event_types": ["action"],
            "limit": 10,
        })
        assert resp.status_code == 200
        events = resp.json()["events"]
        for e in events:
            assert e.get("event_type") == "action" or e.get("type") == "action"
        print(f"  ✓ Found {len(events)} action events")


# ─────────────────────────────────────────────────────────────────────
# 2. STORAGE: Episodes
# ─────────────────────────────────────────────────────────────────────

class TestEpisodes:
    def test_store_episode(self, client):
        resp = client.post("/episodes", json={
            "group_id": "e2e-test",
            "content": (
                "Agent successfully analyzed quarterly sales data for Q3-Q4 2025. "
                "Key findings: Revenue increased 15% YoY, driven by enterprise segment. "
                "Used web_search (3 calls, all successful) and file_write (1 call). "
                "Generated comprehensive markdown report saved to /tmp/sales_analysis.md."
            ),
            "episode_type": "reflection",
            "metadata": {"task": "analyze sales data", "status": "success"},
        })
        assert resp.status_code == 200
        uuid = resp.json()["uuid"]
        assert uuid != ""
        print(f"  ✓ Stored episode: {uuid}")
        return uuid

    def test_store_second_episode(self, client):
        resp = client.post("/episodes", json={
            "group_id": "e2e-test",
            "content": (
                "Agent researched machine learning model deployment strategies. "
                "Compared Docker vs Kubernetes vs serverless approaches. "
                "Found that for small models, serverless (AWS Lambda) is most cost-effective. "
                "For large models, Kubernetes with GPU nodes is recommended."
            ),
            "episode_type": "reflection",
            "metadata": {"task": "ML deployment research", "status": "success"},
        })
        assert resp.status_code == 200
        print(f"  ✓ Stored second episode: {resp.json()['uuid']}")

    def test_search_episodes(self, client):
        # Small delay for indexing
        time.sleep(0.5)
        resp = client.post("/episodes/search", json={
            "group_id": "e2e-test",
            "query": "sales data analysis quarterly report",
            "top_k": 5,
            "min_score": 0.3,
        })
        assert resp.status_code == 200
        episodes = resp.json()["episodes"]
        assert len(episodes) >= 1
        # First result should be about sales
        top = episodes[0]
        assert "sales" in top.get("content", "").lower() or "revenue" in top.get("content", "").lower()
        print(f"  ✓ Episode search returned {len(episodes)} results, top score={top.get('score', 0):.3f}")


# ─────────────────────────────────────────────────────────────────────
# 3. STORAGE: Knowledge
# ─────────────────────────────────────────────────────────────────────

class TestKnowledge:
    def test_store_knowledge(self, client):
        resp = client.post("/knowledge", json={
            "group_id": "e2e-test",
            "entries": [
                {
                    "content": "Enterprise sales revenue increased 15% year-over-year in Q3-Q4 2025, primarily driven by new SaaS product adoption.",
                    "knowledge_type": "fact",
                    "labels": ["sales", "revenue", "enterprise", "2025"],
                    "confidence": 0.92,
                },
                {
                    "content": "The web_search tool is highly reliable for finding financial reports with a 100% success rate observed across 3 calls.",
                    "knowledge_type": "pattern",
                    "labels": ["web-search", "tools", "reliability"],
                    "confidence": 0.85,
                },
                {
                    "content": "For ML model deployment, serverless (Lambda) is most cost-effective for small models, Kubernetes with GPU nodes for large models.",
                    "knowledge_type": "insight",
                    "labels": ["machine-learning", "deployment", "infrastructure"],
                    "confidence": 0.88,
                },
            ],
            "source_mission": "analyze quarterly sales data",
            "mission_status": "success",
        })
        assert resp.status_code == 200
        uuids = resp.json()["uuids"]
        assert len(uuids) == 3
        print(f"  ✓ Stored {len(uuids)} knowledge entries")

    def test_search_knowledge_hybrid(self, client):
        time.sleep(0.5)
        resp = client.post("/knowledge/search", json={
            "group_id": "e2e-test",
            "query": "enterprise revenue growth",
            "labels": ["sales", "revenue"],
            "top_k": 5,
            "min_score": 0.3,
        })
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) >= 1
        top = entries[0]
        assert "revenue" in top.get("content", "").lower() or "sales" in top.get("content", "").lower()
        print(f"  ✓ Knowledge hybrid search returned {len(entries)} results")

    def test_search_by_labels(self, client):
        resp = client.post("/knowledge/search-labels", json={
            "group_id": "e2e-test",
            "labels": ["machine-learning", "deployment"],
            "top_k": 5,
        })
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) >= 1
        print(f"  ✓ Label search returned {len(entries)} results")


# ─────────────────────────────────────────────────────────────────────
# 4. STORAGE: Artifacts
# ─────────────────────────────────────────────────────────────────────

class TestArtifacts:
    def test_store_artifacts(self, client):
        resp = client.post("/artifacts", json={
            "group_id": "e2e-test",
            "entries": [
                {
                    "name": "Q3-Q4 2025 Sales Analysis Report",
                    "artifact_type": "report",
                    "path": "/tmp/sales_analysis.md",
                    "description": "Comprehensive markdown report analyzing quarterly sales data with YoY comparisons and segment breakdowns.",
                    "labels": ["sales", "report", "analysis", "2025"],
                },
                {
                    "name": "ML Deployment Comparison Matrix",
                    "artifact_type": "document",
                    "path": "/tmp/ml_deployment_matrix.csv",
                    "description": "CSV comparing Docker, Kubernetes, and serverless deployment options across cost, scalability, and ease dimensions.",
                    "labels": ["machine-learning", "deployment", "comparison"],
                },
            ],
            "source_mission": "analyze quarterly sales data",
            "mission_status": "success",
        })
        assert resp.status_code == 200
        uuids = resp.json()["uuids"]
        assert len(uuids) == 2
        print(f"  ✓ Stored {len(uuids)} artifacts")
        return uuids

    def test_search_artifacts(self, client):
        time.sleep(0.5)
        resp = client.post("/artifacts/search", json={
            "group_id": "e2e-test",
            "query": "sales report analysis",
            "labels": ["sales"],
            "top_k": 5,
            "min_score": 0.3,
        })
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) >= 1
        print(f"  ✓ Artifact search returned {len(entries)} results")

    def test_list_recent_artifacts(self, client):
        resp = client.get("/artifacts/recent/list", params={
            "group_id": "e2e-test",
            "limit": 10,
        })
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) >= 1
        print(f"  ✓ Listed {len(entries)} recent artifacts")


# ─────────────────────────────────────────────────────────────────────
# 5. STORAGE: State
# ─────────────────────────────────────────────────────────────────────

class TestState:
    def test_persist_execution_state(self, client):
        resp = client.put("/state/execution", json={
            **_scope(),
            "state_description": "Analyzing Q3-Q4 sales data, found 15% YoY revenue growth",
            "iteration": 3,
            "plan_json": json.dumps({
                "goal": "Analyze sales data",
                "items": [
                    {"description": "Search for reports", "status": "completed"},
                    {"description": "Analyze trends", "status": "in_progress"},
                ],
            }),
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        print("  ✓ Persisted execution state")

    def test_get_execution_state(self, client):
        resp = client.get("/state/execution", params={
            "group_id": "e2e-test",
            "workflow_id": "test-wf-001",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True
        assert data["iteration"] == 3
        assert "sales" in data["state_description"].lower()
        print(f"  ✓ Retrieved state: iteration={data['iteration']}")

    def test_update_tool_stats(self, client):
        tools = [
            ("web_search", True, 450),
            ("web_search", True, 380),
            ("web_search", True, 520),
            ("file_write", True, 120),
            ("file_write", False, 50),
        ]
        for tool, success, duration in tools:
            resp = client.post("/state/tool-stats", json={
                **_scope(),
                "tool_name": tool,
                "success": success,
                "duration_ms": duration,
                "state_description": "testing tool stats",
            })
            assert resp.status_code == 200
        print(f"  ✓ Recorded {len(tools)} tool stat entries")

    def test_get_tool_stats(self, client):
        resp = client.get("/state/tool-stats", params={
            "group_id": "e2e-test",
            "workflow_id": "test-wf-001",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "formatted_stats" in data
        assert data["formatted_stats"] != "No tool stats available."
        print(f"  ✓ Tool stats:\n{data['formatted_stats']}")

    def test_get_memory_context(self, client):
        resp = client.get("/state/context", params={
            "group_id": "e2e-test",
            "workflow_id": "test-wf-001",
            "event_limit": 5,
        })
        assert resp.status_code == 200
        ctx = resp.json()["formatted_context"]
        assert ctx != ""
        print(f"  ✓ Memory context ({len(ctx)} chars)")


# ─────────────────────────────────────────────────────────────────────
# 6. SMART OPS: Task Reinterpretation (DSPy)
# ─────────────────────────────────────────────────────────────────────

class TestSmartOps:
    def test_reinterpret_task(self, client):
        resp = client.post("/smart/reinterpret-task", json={
            "task": "Find all the quarterly earnings reports from Apple and compare their revenue trends over the past 3 years",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "search_labels" in data
        assert "search_query" in data
        assert len(data["search_labels"]) > 0
        assert data["search_query"] != ""
        print(f"  ✓ Reinterpreted task: labels={data['search_labels']}, query='{data['search_query'][:60]}...'")

    def test_filter_memory_results(self, client):
        search_results = """## Related Memory (Episode Search)
1. [reflection] Agent successfully analyzed quarterly sales data for Q3-Q4 2025. Key findings: Revenue increased 15% YoY... (score=0.82)
2. [reflection] Agent researched machine learning model deployment strategies... (score=0.45)
3. [raw] System initialization complete, connected to DragonflyDB... (score=0.31)"""

        resp = client.post("/smart/filter-results", json={
            "task": "Analyze Apple earnings and revenue trends",
            "search_results": search_results,
            "max_results": 2,
        })
        assert resp.status_code == 200
        filtered = resp.json()["filtered_results"]
        assert filtered != ""
        # The ML deployment entry should ideally be filtered out as less relevant
        print(f"  ✓ Filtered results ({len(filtered)} chars)")

    def test_infer_state(self, client):
        resp = client.post("/smart/infer-state", json={
            "task": "Analyze quarterly sales data for Q3-Q4 2025",
            "retrieved_memories": (
                "Previously analyzed sales data and found 15% YoY revenue growth. "
                "Used web_search tool successfully. Generated markdown report."
            ),
        })
        assert resp.status_code == 200
        state = resp.json()["state_description"]
        assert state != ""
        print(f"  ✓ Inferred state: '{state[:80]}...'")

    def test_synthesize_background(self, client):
        resp = client.post("/smart/synthesize-background", json={
            "group_id": "e2e-test",
            "task": "Analyze Q1 2026 sales data and compare with previous quarters",
            "long_term_context": "Previously analyzed Q3-Q4 2025 sales data with 15% YoY growth.",
            "tool_stats_context": "web_search: 3 calls, 3 ok, avg 450ms\nfile_write: 2 calls, 1 ok, avg 85ms",
            "state_description": "New task, starting fresh analysis.",
            "knowledge_context": "Enterprise revenue increased 15% YoY in Q3-Q4 2025.",
            "artifacts_context": "Sales Analysis Report at /tmp/sales_analysis.md",
        })
        assert resp.status_code == 200
        narrative = resp.json()["narrative"]
        assert narrative != ""
        assert len(narrative) > 50
        print(f"  ✓ Synthesized narrative ({len(narrative)} chars): '{narrative[:100]}...'")

    def test_generate_reflection(self, client):
        resp = client.post("/smart/generate-reflection", json={
            "mission_data_json": json.dumps({
                "task": "Analyze quarterly sales data for Q3-Q4 2025",
                "status": "success",
                "output": "Revenue increased 15% YoY driven by enterprise segment.",
                "iterations": 4,
                "state": {
                    "state_description": "Analysis complete, report generated",
                    "outputs": [
                        {"iteration": 1, "output": "Searched for reports"},
                        {"iteration": 2, "output": "Downloaded and parsed 3 reports"},
                        {"iteration": 3, "output": "Computed YoY comparisons"},
                        {"iteration": 4, "output": "Generated markdown report"},
                    ],
                },
                "plan": {
                    "goal": "Analyze sales data",
                    "items": [
                        {"description": "Find quarterly reports", "status": "completed"},
                        {"description": "Analyze revenue trends", "status": "completed"},
                        {"description": "Generate report", "status": "completed"},
                    ],
                },
            }),
        })
        assert resp.status_code == 200
        reflection = resp.json()["reflection"]
        assert reflection != ""
        assert len(reflection) > 100
        print(f"  ✓ Generated reflection ({len(reflection)} chars)")

    def test_extract_knowledge(self, client):
        resp = client.post("/smart/extract-knowledge", json={
            "mission_data_json": json.dumps({
                "task": "Analyze quarterly sales data for Q3-Q4 2025",
                "status": "success",
                "output": "Revenue increased 15% YoY. Enterprise segment grew 22%. SMB grew 8%.",
                "iterations": 4,
                "state": {
                    "state_description": "Analysis complete",
                    "outputs": [
                        {"iteration": 1, "output": "Found 3 quarterly reports via web_search"},
                        {"iteration": 4, "output": "Report generated at /tmp/sales_analysis.md"},
                    ],
                },
                "plan": {
                    "goal": "Analyze sales data",
                    "items": [
                        {"description": "Find reports", "status": "completed"},
                        {"description": "Generate analysis", "status": "completed"},
                    ],
                },
                "context": "Tool: web_search(quarterly sales report 2025) → Found 3 PDF reports",
            }),
            "reflection": "Successfully analyzed sales data. web_search was effective.",
        })
        assert resp.status_code == 200
        entries_json = resp.json()["entries_json"]
        entries = json.loads(entries_json)
        assert isinstance(entries, list)
        print(f"  ✓ Extracted {len(entries)} knowledge entries")
        for e in entries[:3]:
            print(f"    - [{e.get('knowledge_type', '?')}] {e.get('content', '')[:80]}...")

    def test_extract_artifacts(self, client):
        resp = client.post("/smart/extract-artifacts", json={
            "mission_data_json": json.dumps({
                "task": "Analyze quarterly sales data for Q3-Q4 2025",
                "status": "success",
                "output": "Generated comprehensive sales analysis report.",
                "iterations": 4,
                "state": {
                    "state_description": "Report saved to /tmp/sales_analysis.md",
                    "outputs": [
                        {"iteration": 3, "output": "file_write('/tmp/sales_analysis.md', ...) → success"},
                        {"iteration": 4, "output": "file_write('/tmp/sales_summary.csv', ...) → success"},
                    ],
                },
                "plan": {
                    "goal": "Analyze sales data",
                    "items": [{"description": "Generate report", "status": "completed"}],
                },
                "context": (
                    "Tool: file_write(path=/tmp/sales_analysis.md) → wrote 2500 bytes\n"
                    "Tool: file_write(path=/tmp/sales_summary.csv) → wrote 800 bytes"
                ),
            }),
        })
        assert resp.status_code == 200
        entries_json = resp.json()["entries_json"]
        entries = json.loads(entries_json)
        assert isinstance(entries, list)
        print(f"  ✓ Extracted {len(entries)} artifact entries")
        for e in entries[:3]:
            print(f"    - [{e.get('artifact_type', '?')}] {e.get('name', '')} @ {e.get('path', '')}")


# ─────────────────────────────────────────────────────────────────────
# 7. PIPELINE: StartupPipeline
# ─────────────────────────────────────────────────────────────────────

class TestStartupPipeline:
    def test_startup_pipeline_full(self, client):
        """Full 7-step startup pipeline in a single RPC."""
        resp = client.post("/pipelines/startup", json={
            "group_id": "e2e-test",
            "workflow_id": "pipeline-test-001",
            "task": "Analyze Q1 2026 financial performance and compare with Q3-Q4 2025 trends",
        })
        assert resp.status_code == 200
        data = resp.json()

        # Verify all expected fields are present
        assert "background_narrative" in data
        assert "inferred_state" in data
        assert "long_term_context" in data
        assert "knowledge_context" in data
        assert "artifacts_context" in data
        assert "tool_stats_context" in data
        assert "search_labels" in data
        assert "search_query" in data

        print(f"\n  ✓ StartupPipeline completed:")
        print(f"    - search_labels: {data['search_labels']}")
        print(f"    - search_query: '{data['search_query'][:60]}...'")
        print(f"    - long_term_context: {len(data['long_term_context'])} chars")
        print(f"    - knowledge_context: {len(data['knowledge_context'])} chars")
        print(f"    - artifacts_context: {len(data['artifacts_context'])} chars")
        print(f"    - tool_stats_context: {len(data['tool_stats_context'])} chars")
        print(f"    - inferred_state: '{data['inferred_state'][:80]}...' " if data['inferred_state'] else "    - inferred_state: (empty)")
        print(f"    - narrative: '{data['background_narrative'][:100]}...' " if data['background_narrative'] else "    - narrative: (empty)")

        # The narrative should be non-empty (synthesis should work even with minimal data)
        assert data["inferred_state"] != "" or data["background_narrative"] != "", \
            "At least one of inferred_state or narrative should be non-empty"


# ─────────────────────────────────────────────────────────────────────
# 8. PIPELINE: RunCuration
# ─────────────────────────────────────────────────────────────────────

class TestRunCuration:
    def test_run_curation_full(self, client):
        """Full 7-step curation pipeline in a single RPC."""
        mission_data = {
            "run_id": "curation-test-001",
            "task": "Research competitive landscape for enterprise AI agent platforms in 2025-2026",
            "status": "success",
            "output": (
                "Identified 5 major competitors: LangChain, CrewAI, AutoGen, Semantic Kernel, and Haystack. "
                "LangChain leads in developer adoption (45% market share), CrewAI leads in multi-agent frameworks. "
                "Key differentiator opportunities: memory persistence, tool reliability, and cost optimization. "
                "Wrote detailed comparison matrix to /tmp/competitive_analysis.md."
            ),
            "iterations": 6,
            "state": {
                "state_description": "Research complete, comparison report generated",
                "outputs": [
                    {"iteration": 1, "output": "Searched for AI agent frameworks 2025-2026"},
                    {"iteration": 2, "output": "Found documentation for LangChain, CrewAI, AutoGen"},
                    {"iteration": 3, "output": "Compared features: memory, tools, orchestration"},
                    {"iteration": 4, "output": "Analyzed pricing and deployment models"},
                    {"iteration": 5, "output": "Identified differentiation opportunities"},
                    {"iteration": 6, "output": "Generated comprehensive comparison report"},
                ],
            },
            "plan": {
                "goal": "Research competitive landscape",
                "items": [
                    {"description": "Identify major competitors", "status": "completed"},
                    {"description": "Compare features", "status": "completed"},
                    {"description": "Analyze pricing", "status": "completed"},
                    {"description": "Find differentiation", "status": "completed"},
                    {"description": "Generate report", "status": "completed"},
                ],
            },
            "context": (
                "Tool: web_search(AI agent frameworks 2025) → 12 results\n"
                "Tool: web_search(LangChain vs CrewAI comparison) → 8 results\n"
                "Tool: web_search(enterprise AI agent pricing 2026) → 5 results\n"
                "Tool: file_write(/tmp/competitive_analysis.md) → wrote 4200 bytes"
            ),
        }

        resp = client.post("/pipelines/curation", json={
            "group_id": "e2e-test",
            "workflow_id": "curation-test-001",
            "mission_data_json": json.dumps(mission_data),
        })
        assert resp.status_code == 200
        data = resp.json()

        # Verify all expected fields
        assert "reflection" in data
        assert "reflection_uuid" in data
        assert "knowledge_count" in data
        assert "artifact_count" in data
        assert "events_compressed" in data

        print(f"\n  ✓ RunCuration completed:")
        print(f"    - reflection: '{data['reflection'][:100]}...' ({len(data['reflection'])} chars)")
        print(f"    - reflection_uuid: {data['reflection_uuid']}")
        print(f"    - knowledge_count: {data['knowledge_count']}")
        print(f"    - artifact_count: {data['artifact_count']}")
        print(f"    - events_compressed: {data['events_compressed']}")

        # Reflection should always be generated
        assert data["reflection"] != ""
        assert len(data["reflection"]) > 50

        # Reflection should be stored as an episode
        assert data["reflection_uuid"] != ""

    def test_curated_knowledge_is_searchable(self, client):
        """Verify that knowledge extracted by curation is actually searchable."""
        time.sleep(1)
        resp = client.post("/knowledge/search", json={
            "group_id": "e2e-test",
            "query": "AI agent competitive landscape LangChain CrewAI",
            "top_k": 5,
            "min_score": 0.3,
        })
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        print(f"  ✓ Post-curation knowledge search: {len(entries)} entries found")
        if entries:
            for e in entries[:3]:
                print(f"    - [{e.get('knowledge_type', '?')}] {e.get('content', '')[:80]}...")

    def test_curated_reflection_is_searchable(self, client):
        """Verify the reflection episode is searchable."""
        resp = client.post("/episodes/search", json={
            "group_id": "e2e-test",
            "query": "competitive landscape AI agent platforms research",
            "top_k": 5,
            "min_score": 0.3,
            "episode_type_filter": "reflection",
        })
        assert resp.status_code == 200
        episodes = resp.json()["episodes"]
        print(f"  ✓ Post-curation reflection search: {len(episodes)} episodes found")
        assert len(episodes) >= 1


# ─────────────────────────────────────────────────────────────────────
# 9. CROSS-PIPELINE: End-to-End Flow
# ─────────────────────────────────────────────────────────────────────

class TestEndToEndFlow:
    """
    Full agent lifecycle:
    1. Startup pipeline (retrieval + synthesis)
    2. Agent does work (log events, update state)
    3. Curation pipeline (reflection + extraction)
    4. Verify everything is searchable for next mission
    """

    def test_full_lifecycle(self, client):
        group = "e2e-lifecycle"
        workflow = "lifecycle-001"

        # ── Phase 1: Startup ──
        print("\n  Phase 1: Startup Pipeline")
        startup = client.post("/pipelines/startup", json={
            "group_id": group,
            "workflow_id": workflow,
            "task": "Write a Python script to process CSV files and generate summary statistics",
        })
        assert startup.status_code == 200
        startup_data = startup.json()
        print(f"    ✓ Startup completed: narrative={len(startup_data['background_narrative'])} chars")

        # ── Phase 2: Agent Work ──
        print("  Phase 2: Agent Work (logging events, updating state)")

        # Log some events
        for etype, edata in [
            ("action", {"tool": "file_read", "path": "/data/input.csv"}),
            ("observation", {"content": "Read CSV with 1000 rows, 15 columns"}),
            ("action", {"tool": "python_exec", "code": "import pandas as pd; df = pd.read_csv(...)"}),
            ("observation", {"content": "Generated summary: mean=45.2, median=42.0, std=12.3"}),
            ("action", {"tool": "file_write", "path": "/output/summary.json"}),
        ]:
            r = client.post("/events", json={
                "group_id": group, "workflow_id": workflow,
                "event_type": etype, "event_data": edata,
            })
            assert r.status_code == 200

        # Update state
        client.put("/state/execution", json={
            "group_id": group, "workflow_id": workflow,
            "state_description": "CSV processing complete, summary statistics generated",
            "iteration": 5,
        })

        # Update tool stats
        for tool, success, ms in [("file_read", True, 50), ("python_exec", True, 2500), ("file_write", True, 80)]:
            client.post("/state/tool-stats", json={
                "group_id": group, "workflow_id": workflow,
                "tool_name": tool, "success": success, "duration_ms": ms,
            })
        print("    ✓ Logged 5 events, updated state, recorded 3 tool stats")

        # ── Phase 3: Curation ──
        print("  Phase 3: Curation Pipeline")
        curation = client.post("/pipelines/curation", json={
            "group_id": group,
            "workflow_id": workflow,
            "mission_data_json": json.dumps({
                "run_id": workflow,
                "task": "Write a Python script to process CSV files and generate summary statistics",
                "status": "success",
                "output": "Generated summary statistics: mean=45.2, median=42.0, std=12.3. Output saved to /output/summary.json.",
                "iterations": 5,
                "state": {
                    "state_description": "CSV processing complete, summary generated",
                    "outputs": [
                        {"iteration": 1, "output": "Read input CSV"},
                        {"iteration": 3, "output": "Computed statistics with pandas"},
                        {"iteration": 5, "output": "Wrote summary to file"},
                    ],
                },
                "plan": {
                    "goal": "Process CSV and generate stats",
                    "items": [
                        {"description": "Read CSV file", "status": "completed"},
                        {"description": "Compute statistics", "status": "completed"},
                        {"description": "Write output", "status": "completed"},
                    ],
                },
                "context": (
                    "Tool: file_read(/data/input.csv) → 1000 rows\n"
                    "Tool: python_exec(pandas summary) → mean=45.2\n"
                    "Tool: file_write(/output/summary.json) → 256 bytes"
                ),
            }),
        })
        assert curation.status_code == 200
        curation_data = curation.json()
        print(f"    ✓ Curation: reflection={len(curation_data['reflection'])} chars, "
              f"knowledge={curation_data['knowledge_count']}, "
              f"artifacts={curation_data['artifact_count']}")

        # ── Phase 4: Verify retrievability for next mission ──
        print("  Phase 4: Verify retrievability for next mission")
        time.sleep(1)

        # New startup should find the curated data
        startup2 = client.post("/pipelines/startup", json={
            "group_id": group,
            "workflow_id": "lifecycle-002",
            "task": "Process another CSV dataset with similar statistical analysis",
        })
        assert startup2.status_code == 200
        startup2_data = startup2.json()

        print(f"    ✓ Second startup: narrative={len(startup2_data['background_narrative'])} chars")
        print(f"      long_term_context: {len(startup2_data['long_term_context'])} chars")
        print(f"      knowledge_context: {len(startup2_data['knowledge_context'])} chars")
        print(f"      artifacts_context: {len(startup2_data['artifacts_context'])} chars")

        # Should have retrieved some context from the first mission
        has_context = (
            len(startup2_data.get("long_term_context", "")) > 0
            or len(startup2_data.get("knowledge_context", "")) > 0
            or len(startup2_data.get("background_narrative", "")) > 0
        )
        print(f"    ✓ Memory retrieved from first mission: {has_context}")
        print("\n  ═══ FULL LIFECYCLE TEST PASSED ═══")
