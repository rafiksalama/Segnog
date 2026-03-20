# Segnog REST API Reference

All endpoints are served under the prefix `/api/v1/memory`. Base URL: `http://localhost:9000/api/v1/memory`

## API Exploration

| URL | What it serves |
|---|---|
| `GET /api/v1/memory` | Discovery manifest — links to all endpoint groups and spec URLs |
| `GET /api/v1/memory/openapi.json` | Full OpenAPI 3.x spec (machine-readable JSON) |
| `GET /api/v1/memory/docs` | Swagger UI — interactive browser exploration |
| `GET /api/v1/memory/redoc` | ReDoc — alternative rendered documentation |

---

## Table of Contents

- [Observe](#observe) — the main entry point
- [Episodes](#episodes) — raw memory units
- [Knowledge](#knowledge) — extracted facts
- [Artifacts](#artifacts) — files, outputs, and produced items
- [Events](#events) — DragonflyDB stream events
- [State](#state) — execution state and tool stats
- [Smart](#smart) — LLM-powered operations
- [Pipelines](#pipelines) — composite multi-step operations
- [UI / Dashboard](#ui--dashboard) — read-only queries for the dashboard

---

## Observe

The primary endpoint. Call it at every agent turn — it stores the observation, retrieves related memory, and returns a formatted context string ready to inject into your next LLM prompt.

### `POST /observe`

```json
{
  "session_id": "my-agent-42",
  "content": "User asked about last quarter's deployment incident.",
  "parent_session_id": null,
  "timestamp": "2025-11-01T14:30:00Z",
  "source": "chat",
  "metadata": {},
  "read_only": false,
  "summarize": false,
  "top_k": 100,
  "knowledge_top_k": 10,
  "minimal": false
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `session_id` | string | **required** | Identifies the session. All episodes and context are scoped to this ID. |
| `content` | string | **required** | The current observation — a message, event, or any text the agent sees. |
| `parent_session_id` | string\|null | `null` | Links this session as a child of another. Child sessions inherit ancestor context at query time. See [Hierarchical Sessions](#hierarchical-sessions). |
| `timestamp` | string\|null | now | ISO 8601 string or Unix epoch. Defaults to server time. |
| `source` | string\|null | `null` | Who or what generated this observation (e.g. `"chat"`, `"tool"`, `"system"`). |
| `metadata` | object | `{}` | Arbitrary key-value metadata stored with the episode. |
| `read_only` | bool | `false` | If `true`, returns context without writing anything. Use for read-only lookups. |
| `summarize` | bool | `false` | If `true`, runs LLM summarisation over the retrieved entries before returning. |
| `top_k` | int | `100` | Max session entries to retrieve and score from DragonflyDB. |
| `knowledge_top_k` | int | `10` | Max knowledge entries to pull from FalkorDB for augmentation. |
| `minimal` | bool | `false` | If `true`, skips DragonflyDB entirely — only FalkorDB knowledge + 1 recent episode. |

**Response**

```json
{
  "episode_uuid": "550e8400-e29b-41d4-a716-446655440000",
  "observation_type": "observe",
  "context": "In Q3, the v2.3 deployment caused a memory leak...",
  "search_labels": ["deployment", "incident", "memory-leak"],
  "search_query": "deployment incident memory leak v2.3"
}
```

| Field | Description |
|---|---|
| `episode_uuid` | UUID of the stored episode. Empty on `read_only` calls. |
| `observation_type` | Always `"observe"`. |
| `context` | Ready-to-use memory passage. Inject this directly into your system prompt. |
| `search_labels` | Labels generated on cold-start reinterpretation. |
| `search_query` | Optimised query used for cold-start FalkorDB search. |

### Hierarchical Sessions

Sessions can be nested arbitrarily deep. When a child session calls `/observe`, Segnog automatically resolves all ancestor sessions and includes their memory in the context — the agent in `subtask-1a` sees everything from `task-1` and `project-x` without any extra configuration.

```bash
# Create root session
curl -X POST .../observe \
  -d '{"session_id": "project-x", "content": "Building a search engine"}'

# Create child session
curl -X POST .../observe \
  -d '{"session_id": "task-1", "parent_session_id": "project-x", "content": "Working on indexing pipeline"}'

# Create grandchild session
curl -X POST .../observe \
  -d '{"session_id": "subtask-1a", "parent_session_id": "task-1", "content": "Implementing tokenizer"}'

# Grandchild query — context includes episodes from task-1 AND project-x
curl -X POST .../observe \
  -d '{"session_id": "subtask-1a", "content": "What are we building?", "read_only": true}'
```

Inheritance rules:
- Session links are created lazily on the first write — no pre-registration required.
- A session with no `parent_session_id` is a root session; context is scoped to itself only.
- DragonflyDB short-term cache is always session-scoped (hot path, ephemeral). Inherited context comes from FalkorDB (long-term).
- Re-observing with a different `parent_session_id` does not change an existing link.

---

## Episodes

Raw memory units stored in FalkorDB. Each `/observe` call creates an episode automatically. Use these endpoints for direct access when you need more control.

### `POST /episodes`

Store an episode directly.

```json
{
  "group_id": "my-agent-42",
  "content": "The user approved the deployment plan.",
  "episode_type": "raw",
  "metadata": {"approved_by": "alice"}
}
```

**Response:** `{"uuid": "..."}`

---

### `POST /episodes/search`

Vector search over episodes in FalkorDB.

```json
{
  "group_id": "my-agent-42",
  "query": "deployment approval",
  "top_k": 25,
  "min_score": 0.55,
  "episode_type_filter": null,
  "expand_adjacent": false,
  "expansion_hops": 1,
  "after_time": null,
  "before_time": null
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `query` | string | **required** | Natural-language search query. |
| `top_k` | int | `25` | Max results. |
| `min_score` | float | `0.55` | Minimum cosine similarity threshold. |
| `episode_type_filter` | string\|null | `null` | Filter by `episode_type` (e.g. `"raw"`). |
| `expand_adjacent` | bool | `false` | If `true`, expands results to include graph-adjacent episodes. |
| `expansion_hops` | int | `1` | How many hops to expand. |
| `after_time` / `before_time` | float\|null | `null` | Unix timestamps to restrict the time window. |

**Response:** `{"episodes": [{"uuid", "content", "episode_type", "created_at", "created_at_iso", "score", ...}]}`

---

### `POST /episodes/search/entities`

Search episodes by entity names (matches via ABOUT edges to OntologyNodes).

```json
{
  "group_id": "my-agent-42",
  "entity_names": ["Alice", "deployment"],
  "top_k": 25
}
```

**Response:** Same shape as `/episodes/search`.

---

### `POST /episodes/link`

Create an explicit edge between two episodes.

```json
{
  "group_id": "my-agent-42",
  "from_uuid": "uuid-a",
  "to_uuid": "uuid-b",
  "edge_type": "FOLLOWS",
  "properties": {"reason": "sequential events"}
}
```

**Response:** `{"linked": true}`

---

## Knowledge

Extracted facts stored in FalkorDB with embeddings. Knowledge is extracted automatically from episodes by background workers.

### `POST /knowledge`

Store knowledge entries directly.

```json
{
  "group_id": "my-agent-42",
  "entries": [
    {
      "content": "Alice approved the v2.3 deployment on Oct 14.",
      "knowledge_type": "fact",
      "labels": ["deployment", "approval"],
      "confidence": 0.9,
      "event_date": "2024-10-14"
    }
  ],
  "source_mission": "deployment-review",
  "mission_status": "success",
  "source_episode_uuid": "uuid-of-source-episode"
}
```

**Response:** `{"uuids": ["..."]}`

---

### `POST /knowledge/search`

Vector search over knowledge nodes.

```json
{
  "group_id": "my-agent-42",
  "query": "who approved the deployment",
  "labels": ["deployment"],
  "top_k": 10,
  "min_score": 0.50,
  "start_date": "2024-10-01",
  "end_date": "2024-10-31"
}
```

`labels` narrows to knowledge tagged with any of the provided labels. `start_date` / `end_date` filter by `event_date` (ISO date strings).

**Response:** `{"entries": [{"uuid", "content", "knowledge_type", "labels", "confidence", "score", ...}]}`

---

### `POST /knowledge/search-labels`

Retrieve knowledge by exact label match (no vector search).

```json
{
  "group_id": "my-agent-42",
  "labels": ["deployment", "incident"],
  "top_k": 10
}
```

**Response:** Same shape as `/knowledge/search`.

---

## Artifacts

Files, outputs, and produced items associated with agent missions.

### `POST /artifacts`

Store artifact entries.

```json
{
  "group_id": "my-agent-42",
  "entries": [
    {
      "name": "deployment-plan.md",
      "artifact_type": "file",
      "path": "/workspace/deployment-plan.md",
      "description": "Deployment runbook for v2.4",
      "labels": ["deployment", "runbook"]
    }
  ],
  "source_mission": "deployment-review",
  "mission_status": "success",
  "source_episode_uuid": ""
}
```

**Response:** `{"uuids": ["..."]}`

---

### `POST /artifacts/search`

Vector search over artifacts.

```json
{
  "group_id": "my-agent-42",
  "query": "deployment runbook",
  "labels": ["deployment"],
  "top_k": 10,
  "min_score": 0.45
}
```

**Response:** `{"entries": [{"uuid", "name", "artifact_type", "path", "description", "labels", "score", ...}]}`

---

### `GET /artifacts/{uuid}?group_id=my-agent-42`

Retrieve a single artifact by UUID.

**Response:** `{"artifact": {...}, "found": true}`

---

### `GET /artifacts/recent/list?group_id=my-agent-42&limit=50`

List recent artifacts without search.

**Response:** `{"entries": [...]}`

---

### `DELETE /artifacts/{uuid}?group_id=my-agent-42`

Delete an artifact.

**Response:** `{"existed": true}`

---

## Events

Low-level event stream stored in DragonflyDB. Used by background workers and the dashboard activity feed.

### `POST /events`

Log an event to the stream.

```json
{
  "group_id": "my-agent-42",
  "workflow_id": "run-001",
  "event_type": "tool_call",
  "event_data": {"tool": "bash", "input": "ls /workspace"}
}
```

**Response:** `{"event_id": "stream-id-..."}`

---

### `GET /events/recent?group_id=...&workflow_id=...&count=10&event_type=tool_call`

Retrieve recent events from the stream.

**Response:** `{"events": [{"event_id", "event_type", "timestamp", "group_id", "data", ...}]}`

---

### `POST /events/search`

Filter recent events by type.

```json
{
  "group_id": "my-agent-42",
  "workflow_id": "run-001",
  "event_types": ["tool_call", "observation"],
  "limit": 50
}
```

**Response:** `{"events": [...]}`

---

## State

Execution state and tool statistics stored in DragonflyDB. Used by agents that need to persist planning state across steps.

### `PUT /state/execution`

Persist execution state for a running workflow.

```json
{
  "group_id": "my-agent-42",
  "workflow_id": "run-001",
  "state_description": "Completed indexing; starting ranking phase.",
  "iteration": 3,
  "plan_json": "{...}",
  "judge_json": "{...}"
}
```

**Response:** `{"success": true}`

---

### `GET /state/execution?group_id=...&workflow_id=...`

Retrieve persisted execution state.

**Response:** `{"state_description", "iteration", "plan_json", "judge_json", "found"}`

---

### `POST /state/tool-stats`

Record a tool call outcome for performance tracking.

```json
{
  "tool_name": "bash",
  "state_description": "running indexer",
  "success": true,
  "duration_ms": 140
}
```

**Response:** `{"success": true}`

---

### `GET /state/tool-stats`

Retrieve aggregated tool performance statistics.

**Response:** `{"formatted_stats": "bash: 12 calls, 11 ok, avg 132ms\n...", "raw_stats_json": "{...}"}`

---

### `GET /state/context?group_id=...&workflow_id=...&event_limit=5`

Return a formatted memory context passage from recent DragonflyDB events.

**Response:** `{"formatted_context": "[tool_call] ls /workspace\n..."}`

---

## Smart

LLM-powered operations using DSPy. These are called internally by the observe pipeline but are also available directly.

### `POST /smart/reinterpret-task`

Reinterpret a task description into search labels, a query, and a complexity assessment.

```json
{"task": "Fix the authentication bug in the login flow", "model": null}
```

**Response:** `{"search_labels": [...], "search_query": "...", "complexity": "..."}`

---

### `POST /smart/filter-results`

LLM-powered relevance filter over memory search results.

```json
{
  "task": "Fix the auth bug",
  "search_results": "1. [Memory] ...\n2. [Memory] ...",
  "model": null,
  "max_results": 5
}
```

**Response:** `{"filtered_results": "..."}`

---

### `POST /smart/infer-state`

Infer current agent state from a task and retrieved memories.

```json
{
  "task": "Fix the auth bug",
  "retrieved_memories": "...",
  "model": null
}
```

**Response:** `{"state_description": "..."}`

---

### `POST /smart/synthesize-background`

Synthesize a background narrative from all memory sources.

```json
{
  "group_id": "my-agent-42",
  "task": "Fix the auth bug",
  "long_term_context": "...",
  "knowledge_context": "...",
  "artifacts_context": "...",
  "tool_stats_context": "...",
  "state_description": "...",
  "model": null
}
```

**Response:** `{"background": "...", ...}`

---

### `POST /smart/generate-reflection`

Generate a post-mission reflection.

```json
{"mission_data_json": "{...}", "model": null}
```

**Response:** `{"reflection": "..."}`

---

### `POST /smart/extract-knowledge`

Extract knowledge entries from mission data.

```json
{"mission_data_json": "{...}", "reflection": "...", "model": null}
```

**Response:** `{"entries_json": "[...]"}`

---

### `POST /smart/extract-artifacts`

Extract artifact entries from mission data.

```json
{"mission_data_json": "{...}", "model": null}
```

**Response:** `{"entries_json": "[...]"}`

---

### `POST /smart/extract-relationships`

Extract Schema.org-typed entity relationships from free text.

```json
{
  "text": "Alice works for Acme Corp and knows Bob, the CTO.",
  "model": null
}
```

**Response:**

```json
{
  "relationships": [
    {
      "subject": "Alice",
      "subject_type": "Person",
      "predicate": "worksFor",
      "object": "Acme Corp",
      "object_type": "Organization",
      "confidence": 0.95
    }
  ]
}
```

---

### `POST /smart/update-ontology-node`

Update an OntologyNode's prose summary using LLM synthesis. Optionally upserts the node.

```json
{
  "entity_name": "Alice",
  "schema_type": "Person",
  "existing_summary": "Alice is the lead engineer.",
  "new_episode_text": "Alice approved the v2.3 deployment.",
  "group_id": "my-agent-42",
  "model": null
}
```

**Response:** `{"updated_summary": "...", "uuid": "..."}`

---

### `POST /smart/search-ontology-nodes`

Vector search over OntologyNode summary embeddings.

```json
{
  "query": "who manages deployments",
  "group_id": "my-agent-42",
  "top_k": 5,
  "min_score": 0.3
}
```

**Response:** `{"nodes": [{"uuid", "name", "schema_type", "display_name", "summary", "score"}]}`

---

### `POST /smart/compress-events`

Compress old DragonflyDB events into an episode summary (frees stream space).

```json
{
  "group_id": "my-agent-42",
  "workflow_id": "run-001",
  "run_id": "run-001",
  "state_description": "completed ranking phase",
  "model": null
}
```

**Response:** `{"compressed": true, ...}`

---

## Pipelines

Composite operations that replace multi-step sequences with a single call.

### `POST /pipelines/startup`

Full agent startup pipeline. Runs: reinterpret → search episodes → search knowledge/artifacts (parallel) → filter → tool stats → infer state → synthesize background.

```json
{
  "group_id": "my-agent-42",
  "workflow_id": "run-001",
  "task": "Fix the authentication bug in the login flow",
  "model": null
}
```

**Response:** `{"background": "...", "state_description": "...", "search_labels": [...], ...}`

---

### `POST /pipelines/curation`

Full curation pipeline for a completed mission. Runs: reflect → store reflection → extract knowledge → store knowledge → extract artifacts → store artifacts → compress events.

```json
{
  "group_id": "my-agent-42",
  "workflow_id": "run-001",
  "mission_data_json": "{...}",
  "source_episode_uuids": ["uuid-1", "uuid-2"],
  "model": null
}
```

**Response:** `{"knowledge_uuids": [...], "artifact_uuids": [...], "reflection": "...", ...}`

---

## UI / Dashboard

Read-only endpoints used by the Segnog dashboard. All return live data from FalkorDB and DragonflyDB.

### `GET /ui/stats?group_id=optional`

Aggregate counts across all memory layers.

```json
{
  "episodes": 742,
  "knowledge_nodes": 1413,
  "ontology_entities": 420,
  "active_groups": 124,
  "pending_episodes": 0,
  "hebbian_edges": 1727
}
```

---

### `GET /ui/sessions?limit=200`

List all sessions with episode counts, latest activity, and parent session ID. The dashboard uses this to build the session tree.

```json
{
  "sessions": [
    {
      "group_id": "subtask-1a",
      "episode_count": 2,
      "latest_at": 1773992087.46,
      "parent_session_id": "task-1"
    },
    {
      "group_id": "task-1",
      "episode_count": 2,
      "latest_at": 1773991992.51,
      "parent_session_id": "project-x"
    },
    {
      "group_id": "project-x",
      "episode_count": 2,
      "latest_at": 1773992015.81,
      "parent_session_id": null
    }
  ]
}
```

Root sessions have `parent_session_id: null`. Sessions without a `Session` node (pre-hierarchy data) also appear with `parent_session_id: null`.

---

### `GET /ui/sessions/{session_id}/children`

List direct child sessions of a given session.

```json
{
  "children": [
    {"group_id": "task-1", "created_at": 1773991975.18, "episode_count": 2},
    {"group_id": "task-2", "created_at": 1773992100.00, "episode_count": 1}
  ]
}
```

---

### `GET /ui/episodes?group_id=optional&limit=50`

List recent episodes. Returns all sessions if `group_id` is omitted.

```json
{
  "episodes": [
    {
      "uuid": "...",
      "content": "User asked about deployment.",
      "episode_type": "raw",
      "group_id": "my-agent-42",
      "created_at": 1773992015.81,
      "created_at_iso": "2025-11-01T14:30:15.810000",
      "consolidated": true,
      "knowledge_extracted": true
    }
  ]
}
```

---

### `GET /ui/knowledge?group_id=optional&limit=50`

List recent knowledge nodes with their labels.

---

### `GET /ui/ontology?group_id=optional&schema_type=optional&limit=100`

List OntologyNodes. Filter by `group_id` and/or `schema_type`.

---

### `GET /ui/ontology/edges?limit=300`

Return `RELATES` edges between OntologyNodes for graph visualisation.

```json
{"edges": [{"source": "uuid-a", "target": "uuid-b", "predicate": "worksFor"}]}
```

---

### `GET /ui/ontology/cooccurrence?limit=400`

Return pairs of OntologyNodes that co-occur in the same episode, with co-occurrence weight.

```json
{"edges": [{"source": "uuid-a", "target": "uuid-b", "weight": 7}]}
```

---

### `GET /ui/events?count=20`

Return recent DragonflyDB stream events formatted as `memory.<type>.<group>` subjects.

```json
{"events": [{"subject": "memory.observation.my-agent-42", "time": "14:30:15"}]}
```

---

### `GET /ui/latency`

Per-endpoint latency statistics with recent timestamped samples for realtime charts.

```json
[
  {
    "endpoint": "POST /observe",
    "count": 312,
    "p50": 24,
    "p95": 87,
    "p99": 143,
    "max": 412,
    "mean": 31,
    "samples": [[1773992015.81, 28], [1773992016.04, 31], ...]
  }
]
```

---

## Health

### `GET /health`

```json
{"status": "ok", "service": "agent-memory-service"}
```
