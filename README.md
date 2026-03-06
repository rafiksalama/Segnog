# Segnog

> **Dal Segno** — *from the sign*. In music, the performer returns to the segno mark and replays the passage with everything they've learned. The second time through is never the same as the first.

Segnog is a memory service for AI agents. It stores what happened, distills what mattered, and hands it back at exactly the right moment — so the agent returns to the sign and plays it better.

Short-term event streams. Long-term episodic memory. A knowledge graph. An artifact registry. LLM-powered curation that compresses experience into wisdom. Background offline consolidation inspired by biological memory. All behind dual gRPC and REST APIs.

Every mission is a performance. Segnog is the bookmark the agent jumps back to.

## Architecture Overview

```
                          Agent Framework (caller)
                                  |
                    ┌─────────────┴──────────────┐
                    |                            |
              gRPC :50051                  REST :9000
              (JSON-over-gRPC)             (FastAPI)
                    |                            |
                    └──────────┬─────────────────┘
                               |
                    MemoryServiceHandler
                    (shared business logic)
                               |
            ┌──────────┬───────┴────────┬──────────┐
            |          |                |          |
       DragonflyDB   FalkorDB      LLM Client   DSPy
       (short-term)  (long-term)   (OpenAI API)  (structured
        Redis         Graph DB      via OpenRouter  extraction)
                         |
                    REM Worker
                    (background offline
                     consolidation)
```

The service has two storage tiers, an LLM integration layer, two composite pipelines, and a background consolidation worker.

## Table of Contents

- [Memory Model](#memory-model)
- [Storage Tiers](#storage-tiers)
- [Smart Operations](#smart-operations)
- [Composite Pipelines](#composite-pipelines)
- [Background Consolidation (REM Worker)](#background-consolidation-rem-worker)
- [Data Flow Between Tiers](#data-flow-between-tiers)
- [Graph Schema](#graph-schema)
- [API Reference](#api-reference)
- [Client Library](#client-library)
- [Configuration](#configuration)
- [Running](#running)
- [Testing](#testing)
- [Benchmarks](#benchmarks)
- [Project Structure](#project-structure)

## Memory Model

The service manages five entity types across two storage tiers:

| Entity | Storage | Purpose | Lifecycle |
|--------|---------|---------|-----------|
| **Events** | DragonflyDB (Redis Streams) | Real-time agent activity log | Written during mission, compressed post-mission |
| **Execution State** | DragonflyDB (Redis Hashes) | Agent iteration, plan, judge state | Overwritten each iteration |
| **Episodes** | FalkorDB (Graph nodes + vectors) | Mission traces and reflections | `pending` → `consolidated` via REM worker |
| **Knowledge** | FalkorDB (Graph nodes + vectors + edges) | Extracted facts, patterns, insights | Permanent, searchable by vector + labels |
| **Artifacts** | FalkorDB (Graph nodes + vectors + edges) | Registered outputs (files, reports, datasets) | Permanent, CRUD + search |

All operations are scoped by `group_id` (tenant) and `workflow_id` (workflow instance).

## Storage Tiers

### Tier 1: Short-Term Memory (DragonflyDB)

DragonflyDB is a Redis-compatible in-memory store. The service uses two Redis data structures:

**Events** via Redis Streams (key: `events:{group_id}:{workflow_id}`)

Events are the real-time activity log. Every LLM call, tool invocation, observation, and error is appended as a stream entry. Events are ordered, filterable by type, and retrievable newest-first.

```python
# Event types (framework-agnostic)
"llm_request", "llm_response",
"tool_call", "tool_result",
"action", "observation",
"error", "state_update"
```

Each event contains: `event_id`, `type`, `timestamp`, `group_id`, `workflow_id`, and `data` (arbitrary JSON).

**Execution State** via Redis Hashes (key: `exec_state:{group_id}:{workflow_id}`)

Stores the agent's current state between iterations: `state_description`, `iteration` count, serialized `plan` JSON, and `judge` evaluation JSON. Also stores per-tool usage statistics (call counts, success rates, avg latency) under `state:tool_stats:*` keys.

**ShortTermMemory** is a routing layer that dispatches by key prefix:
- `event:*` keys route to Redis Streams
- `state:*` keys route to Redis Hashes
- Other keys fall back to an in-memory dict

### Tier 2: Long-Term Memory (FalkorDB)

FalkorDB is a graph database with native vector search. All three long-term entity types share a single graph (`episode_store` by default) and are connected through labeled relationships.

**Episodes** store mission execution history as graph nodes with vector embeddings. Four types:
- `raw` — direct mission execution traces (task, output, final state)
- `reflection` — structured post-mission reflections generated by the curation pipeline
- `compressed` — LLM summaries of raw episodes, created by the REM worker
- `narrative` — synthesized background briefings generated during startup

Episodes have a `consolidation_status` field tracking their lifecycle:
- `pending` — raw episodes not yet processed by the REM worker
- `consolidated` — episodes that have been processed (reflections, compressed summaries, narratives are born consolidated)

Consecutive episodes within a group are linked with `FOLLOWS` edges, forming a temporal chain. Search is cosine similarity on the embedding vector with optional graph expansion along FOLLOWS edges.

**Knowledge** stores extracted facts, patterns, and insights as graph nodes. Each entry has:
- `content` — the knowledge text
- `knowledge_type` — one of `fact`, `pattern`, `tool_insight`, `experience`, `conclusion`
- `labels` — normalized semantic tags (e.g., `til-density`, `drug-response-markers`)
- `confidence` — 0.0 to 1.0
- `embedding` — vector for similarity search

Labels are stored as separate `(:Label)` nodes, deduplicated via `MERGE`, and connected to knowledge nodes via `[:HAS_LABEL]` edges. This enables both vector search and graph traversal.

Search is **hybrid**: vector similarity retrieves candidates, then label overlap provides a score boost (`final_score = vector_score + 0.15 * label_match_ratio`).

**Artifacts** track tangible outputs: files written, reports generated, datasets compiled. Same structure as knowledge (embeddings, labels, hybrid search) plus `name`, `artifact_type` (file/report/dataset), and `path`. Supports full CRUD (get by UUID, list recent, delete).

## Smart Operations

Eight LLM-powered operations that add intelligence to raw storage:

| Operation | Engine | Input | Output |
|-----------|--------|-------|--------|
| **Reinterpret Task** | DSPy | Raw user task | `search_labels[]`, `search_query`, `complexity` |
| **Filter Memory** | LLM | Task + raw search results | Relevance-filtered results |
| **Infer State** | LLM | Task + retrieved memories | One-sentence state description |
| **Synthesize Background** | LLM | Task + episodes + knowledge + artifacts + tool stats | Natural-language briefing paragraph |
| **Generate Reflection** | LLM | Mission data (task, output, plan, iterations) | Structured 7-section reflection |
| **Extract Knowledge** | DSPy | Mission data + reflection | Structured `[{content, type, labels, confidence}]` |
| **Extract Artifacts** | DSPy | Mission data + execution trace | Structured `[{name, type, path, description, labels}]` |
| **Compress Events** | LLM | Last 50 events from DragonflyDB | Single compressed episode in FalkorDB |

**DSPy** is used for structured extraction (knowledge, artifacts, task reinterpretation) because it enforces output schemas via Pydantic validation and auto-retries on parse failures. It uses a `DirectJSONAdapter` that requests `json_object` response format through OpenRouter.

**Plain LLM calls** are used for free-form text generation (reflection, synthesis, filtering, state inference) via an `AsyncOpenAI` client pointed at OpenRouter.

## Composite Pipelines

Two pipelines reduce multi-step workflows to single RPCs:

### Startup Pipeline

Runs at the beginning of a mission. Retrieves all relevant context and synthesizes a briefing.

```
Step 0: reinterpret_task(task)
        → search_labels[], search_query, complexity
                |
Step 1: episode_store.search_episodes(search_query)
        → raw episode results
                |
Step 2: knowledge_store.search_hybrid(query, labels)  ─┐  parallel
        artifact_store.search_hybrid(query, labels)    ─┘
        → knowledge_context, artifacts_context
                |
Step 3: filter_memory_results(task, episode_results)
        → filtered long_term_context
                |
Step 4: get_tool_stats()
        → formatted tool experience stats
                |
Step 5: infer_state(task, long_term_context)
        → one-sentence state description
                |
Step 6: synthesize_background(task, all_context)
        → natural-language briefing paragraph
        → also stored as "narrative" episode in FalkorDB
```

Returns all fields in a single response so the caller can inject them into the agent's system prompt.

### Curation Pipeline

Runs after a mission completes. Promotes volatile short-term data into permanent long-term memory.

```
Step 1: generate_reflection(mission_data)
        → structured reflection text
                |
Step 2: episode_store.store_episode(reflection, type="reflection")
        → reflection_uuid
                |
Step 2b: link reflection → source raw episodes (DERIVED_FROM edges)
        → source traceability
                |
Step 3: extract_knowledge(mission_data, reflection)
        → knowledge entries with types, labels, confidence
                |
Step 4: knowledge_store.store_knowledge(entries, source_episode=reflection_uuid)
        → knowledge UUIDs, Label nodes, HAS_LABEL + DERIVED_FROM edges
                |
Step 5: extract_artifacts(mission_data)
        → artifact entries with names, types, paths, labels
                |
Step 6: artifact_store.store_artifacts(entries, source_episode=reflection_uuid)
        → artifact UUIDs, Label nodes, HAS_LABEL + DERIVED_FROM edges
                |
Step 7: compress_events(last 50 events from DragonflyDB)
        → compressed episode (LLM summary) stored in FalkorDB
```

## Background Consolidation (REM Worker)

The REM (Replay-Enhanced Memory) worker is a background process inspired by biological sleep-dependent memory consolidation. It periodically scans for unprocessed raw episodes and consolidates them into higher-level representations.

### How It Works

1. **Priority-scored discovery**: Queries for groups with `pending` raw episodes, scores them by `raw_count * 0.5 + age_hours * 0.5` — groups with more unprocessed episodes and older pending episodes are processed first.

2. **Consolidation per group**:
   - Fetches pending raw episodes (oldest first, up to 20)
   - Runs the curation pipeline with `source_episode_uuids` for full provenance tracking
   - Marks source episodes as `consolidated` (durable lifecycle transition in FalkorDB)
   - Creates a `compressed` summary episode with `DERIVED_FROM` edges back to each source

3. **Idempotency**: Once episodes are marked `consolidated`, they are never reprocessed. State is durable in FalkorDB, surviving service restarts.

### Configuration

```toml
[default.background]
enabled = true
interval_seconds = 60        # How often cycles run
batch_size = 5               # Max groups per cycle
min_episodes_for_processing = 3  # Minimum raw episodes before a group is eligible
```

### Graph Structure After Consolidation

```
Knowledge ─[DERIVED_FROM]→ Reflection ─[DERIVED_FROM]→ Raw Episode
Compressed ─[DERIVED_FROM]→ Raw Episode
Episode ─[FOLLOWS]→ Episode  (temporal chain)
```

## Data Flow Between Tiers

Data moves from short-term to long-term memory through the curation pipeline and the REM worker. Curation is triggered explicitly by the caller; the REM worker runs automatically in the background.

```
Agent actions ──► Events (DragonflyDB, Redis Streams)
                      |
                      |  [Curation Pipeline - called by agent framework]
                      |
                      ├──► compress_events() ──► Episode (type="compressed")
                      |
     mission_data ────┤
     (from caller)    ├──► generate_reflection() ──► Episode (type="reflection")
                      |                                   |
                      ├──► extract_knowledge() ────► Knowledge nodes
                      |    (DSPy)                    + Label nodes + edges
                      |                              + DERIVED_FROM → Episode
                      |
                      └──► extract_artifacts() ────► Artifact nodes
                           (DSPy)                    + Label nodes + edges
                                                     + DERIVED_FROM → Episode

     [REM Worker - runs automatically in background]

     Raw episodes ──► priority scoring ──► curation pipeline
     (pending)           |                      |
                         |                      ├──► Reflection + DERIVED_FROM → Raw Episodes
                         |                      ├──► Knowledge extraction
                         |                      └──► Compressed summary + DERIVED_FROM → Raw Episodes
                         |
                         └──► mark episodes as "consolidated"
```

## Graph Schema

All long-term entities live in a single FalkorDB graph:

```
(:Episode) ─[:FOLLOWS]→ (:Episode)                        # temporal chain
(:Episode) ←[:DERIVED_FROM]─ (:Episode)                    # compressed/reflection → raw
(:Episode) ←[:DERIVED_FROM]─ (:Knowledge) ─[:HAS_LABEL]→ (:Label)
(:Episode) ←[:DERIVED_FROM]─ (:Artifact)  ─[:HAS_LABEL]→ (:Label)
```

**Node types:**

| Node | Key Properties | Indexed On |
|------|---------------|------------|
| `Episode` | uuid, group_id, content, episode_type, consolidation_status, metadata, created_at, created_at_iso, embedding | uuid, group_id, episode_type, created_at, consolidation_status |
| `Knowledge` | uuid, group_id, content, knowledge_type, labels, confidence, source_mission, created_at, embedding | uuid, group_id, knowledge_type, created_at |
| `Artifact` | uuid, group_id, name, artifact_type, path, description, labels, source_mission, created_at, embedding | uuid, group_id, artifact_type, created_at |
| `Label` | name, created_at | name |

**Edge types:**

| Edge | From | To | Meaning |
|------|------|-----|---------|
| `FOLLOWS` | Episode | Episode | Temporal ordering within a group |
| `DERIVED_FROM` | Knowledge or Artifact | Episode | Provenance — which reflection this was extracted from |
| `DERIVED_FROM` | Episode (reflection/compressed) | Episode (raw) | Source traceability — which raw episodes were consolidated |
| `HAS_LABEL` | Knowledge or Artifact | Label | Semantic tag association |

Labels are normalized before storage: `"Web Search"` → `"web-search"`, `"web_search"` → `"web-search"`. This deduplication ensures consistent graph traversal.

## API Reference

Base URL: `http://localhost:9000/api/v1/memory`

### Events

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/events` | Log an event |
| GET | `/events/recent` | Get recent events (newest first) |
| POST | `/events/search` | Search events by type filter |

### Episodes

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/episodes` | Store an episode with embedding |
| POST | `/episodes/search` | Vector similarity search |
| POST | `/episodes/link` | Create edge between episodes |

### Knowledge

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/knowledge` | Store knowledge entries with labels |
| POST | `/knowledge/search` | Hybrid search (vector + label boost) |
| POST | `/knowledge/search-labels` | Label-only search via graph edges |

### Artifacts

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/artifacts` | Store artifact entries |
| POST | `/artifacts/search` | Hybrid search (vector + label boost) |
| GET | `/artifacts/{uuid}` | Get artifact by UUID |
| GET | `/artifacts/recent/list` | List recent artifacts |
| DELETE | `/artifacts/{uuid}` | Delete artifact |

### State

| Method | Endpoint | Description |
|--------|----------|-------------|
| PUT | `/state/execution` | Persist execution state |
| GET | `/state/execution` | Get execution state |
| POST | `/state/tool-stats` | Update tool usage statistics |
| GET | `/state/tool-stats` | Get formatted tool stats |
| GET | `/state/context` | Get formatted memory context |

### Smart Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/smart/reinterpret-task` | DSPy task reinterpretation |
| POST | `/smart/filter-results` | LLM relevance filter |
| POST | `/smart/infer-state` | LLM state inference |
| POST | `/smart/synthesize-background` | LLM background narrative |
| POST | `/smart/generate-reflection` | LLM post-mission reflection |
| POST | `/smart/extract-knowledge` | DSPy knowledge extraction |
| POST | `/smart/extract-artifacts` | DSPy artifact extraction |
| POST | `/smart/compress-events` | LLM event compression |

### Pipelines

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/pipelines/startup` | Full 7-step startup sequence |
| POST | `/pipelines/curation` | Full 7-step curation sequence |

### gRPC

All the same operations are available via gRPC on port 50051 using JSON-over-gRPC (generic handler). Method names map directly: `/memory.v1.MemoryService/LogEvent`, `/memory.v1.MemoryService/StartupPipeline`, etc.

Proto definitions are in `proto/memory/v1/` for documentation and future compiled stub generation.

## Client Library

A unified async client supporting both transports:

```python
from memory_client import MemoryClient

# Connect via REST
client = await MemoryClient.rest("http://localhost:9000", group_id="my-agent")

# Or via gRPC
client = await MemoryClient.grpc("localhost:50051", group_id="my-agent")

# Log events
await client.log_event("observation", {"content": "Found 3 reports"})

# Store and search episodes
uuid = await client.store_episode("Agent completed sales analysis...")
results = await client.search_episodes("quarterly sales report")

# Store and search knowledge
await client.store_knowledge(
    entries=[{"content": "Revenue up 15%", "knowledge_type": "fact",
              "labels": ["sales", "revenue"], "confidence": 0.92}],
    source_mission="analyze Q3-Q4 sales",
)
results = await client.search_knowledge("revenue growth", labels=["sales"])

# Run pipelines
startup = await client.startup_pipeline("Analyze Q1 2026 financials")
curation = await client.run_curation(mission_data)

# Fire-and-forget (non-blocking)
client.log_event_fire_and_forget("tool_call", {"tool": "web_search"})
client.update_tool_stats_fire_and_forget("web_search", success=True, duration_ms=450)

await client.close()
```

## Configuration

Configuration is managed via Dynaconf with `settings.toml` and environment variable overrides.

### settings.toml

```toml
[default]
service_name = "agent-memory-service"
version = "0.1.0"

[default.grpc]
port = 50051
max_workers = 10

[default.rest]
host = "0.0.0.0"
port = 9000

[default.dragonfly]
url = "redis://localhost:6381"

[default.falkordb]
url = "redis://localhost:6380"
graph_name = "episode_store"

[default.embeddings]
model = "qwen/qwen3-embedding-8b"
base_url = "https://openrouter.ai/api/v1"

[default.llm]
flash_model = "x-ai/grok-4.1-fast"
base_url = "https://openrouter.ai/api/v1"

[default.dspy]
models = ["deepseek/deepseek-v3.2", "x-ai/grok-4.1-fast"]

[default.background]
enabled = true
interval_seconds = 60
batch_size = 5
min_episodes_for_processing = 3
```

### Environment Overrides

```bash
MEMORY_SERVICE_DRAGONFLY__URL=redis://localhost:6381
MEMORY_SERVICE_FALKORDB__URL=redis://localhost:6380
MEMORY_SERVICE_EMBEDDINGS__API_KEY=sk-or-...
MEMORY_SERVICE_LLM__API_KEY=sk-or-...
```

API keys go in `.secrets.toml` (gitignored) or environment variables.

## Running

### Prerequisites

- Python 3.11+
- Docker (for DragonflyDB and FalkorDB)
- OpenRouter API key (or any OpenAI-compatible endpoint)

### Quick Start

```bash
# Start storage backends
docker-compose up -d dragonfly falkordb

# Install the service
pip install -e ".[dev]"

# Configure API key
export MEMORY_SERVICE_EMBEDDINGS__API_KEY=sk-or-...
export MEMORY_SERVICE_LLM__API_KEY=sk-or-...

# Run
python -m memory_service.main
```

The service starts both servers and the REM worker concurrently:
- gRPC on `localhost:50051`
- REST on `localhost:9000`
- REM worker (background consolidation, every 60s)

Health check: `GET http://localhost:9000/health`

### Docker Compose (full stack)

```bash
export OPENROUTER_API_KEY=sk-or-...
docker-compose up
```

This starts DragonflyDB (`:6381`), FalkorDB (`:6380`), and the memory service (`:50051` + `:9000`).

## Testing

```bash
# Run all tests (requires running service + backends)
pytest tests/ -v -s

# Integration tests only
pytest tests/integration/ -v -s
```

The E2E test suite (`tests/integration/test_e2e_full.py`) covers 30 tests across all layers:
- Storage operations (events, episodes, knowledge, artifacts, state)
- Smart operations (reinterpret, filter, synthesize, reflect, extract)
- Composite pipelines (startup, curation)
- Full agent lifecycle (startup → work → curate → verify retrieval)

## Benchmarks

The service is benchmarked against the [LoCoMo](https://arxiv.org/abs/2402.10790) dataset — 10 long conversations (272 sessions) with 1,986 QA pairs across 5 categories:

| Category | Description | Count | F1 Score |
|----------|-------------|-------|----------|
| 1. Single-hop | Direct factual recall | 282 | 0.564 |
| 2. Temporal | Time-dependent questions | 321 | 0.691 |
| 3. Multi-hop | Multi-step reasoning | 96 | 0.366 |
| 4. Open-domain | Broad knowledge questions | 841 | 0.683 |
| 5. Adversarial | Trick/misleading questions | 446 | 0.962 |
| **Overall (1-4)** | **Excluding adversarial** | **1540** | **0.643** |
| **Overall (1-5)** | **All categories** | **1986** | **0.715** |

*Measured with qwen3-embedding-8b embeddings and grok-4.1-fast answer generation.*

## Project Structure

```
Segnog/
├── src/memory_service/
│   ├── main.py                       # Entry point — starts gRPC + REST + REM worker
│   ├── config.py                     # Dynaconf configuration
│   ├── storage/
│   │   ├── dragonfly.py              # DragonflyDB client (Streams + Hashes)
│   │   ├── short_term.py             # Routing layer (event/state/memory)
│   │   ├── episode_store.py          # Episode storage + vector search + lifecycle
│   │   ├── knowledge_store.py        # Knowledge graph + hybrid search
│   │   └── artifact_store.py         # Artifact registry + hybrid search
│   ├── background/
│   │   └── rem_worker.py             # REM sleep consolidation worker
│   ├── grpc/
│   │   ├── server.py                 # Generic JSON-over-gRPC server
│   │   └── service_handler.py        # Shared business logic (all operations)
│   ├── rest/
│   │   ├── app.py                    # FastAPI app factory
│   │   ├── dependencies.py           # Dependency injection
│   │   └── routers/
│   │       ├── events.py             # Event endpoints
│   │       ├── episodes.py           # Episode endpoints
│   │       ├── knowledge.py          # Knowledge endpoints
│   │       ├── artifacts.py          # Artifact endpoints
│   │       ├── state.py              # State endpoints
│   │       ├── smart.py              # Smart operation endpoints
│   │       └── pipelines.py          # Pipeline endpoints
│   ├── smart/
│   │   ├── reinterpret.py            # DSPy task reinterpretation
│   │   ├── filter.py                 # LLM relevance filter
│   │   ├── infer_state.py            # LLM state inference
│   │   ├── synthesize.py             # LLM background narrative
│   │   ├── reflect.py                # LLM post-mission reflection
│   │   ├── extract_knowledge.py      # DSPy knowledge extraction
│   │   ├── extract_artifacts.py      # DSPy artifact extraction
│   │   └── compress.py               # LLM event compression
│   ├── llm/
│   │   ├── client.py                 # AsyncOpenAI singleton
│   │   └── dspy_adapter.py           # DSPy LM config + DirectJSONAdapter
│   ├── dto/                          # Pydantic request/response models
│   │   ├── events.py
│   │   ├── episodes.py
│   │   ├── knowledge.py
│   │   ├── artifacts.py
│   │   ├── state.py
│   │   └── pipelines.py
│   └── dspy_signatures/              # DSPy prompt templates
│       ├── knowledge_signature.py    # Task reinterpretation + knowledge extraction
│       └── artifact_signature.py     # Artifact extraction
├── client/memory_client/
│   ├── client.py                     # MemoryClient (unified async client)
│   ├── rest_transport.py             # httpx-based REST transport
│   ├── grpc_transport.py             # gRPC JSON transport
│   └── exceptions.py
├── proto/memory/v1/                  # Protocol Buffer definitions
│   ├── common.proto
│   ├── events.proto
│   ├── episodes.proto
│   ├── knowledge.proto
│   ├── artifacts.proto
│   ├── state.proto
│   ├── smart.proto
│   └── pipelines.proto
├── tests/
│   ├── integration/
│   │   └── test_e2e_full.py          # 30 E2E tests
│   └── unit/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── settings.toml
└── README.md
```

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| REST API | FastAPI + uvicorn | HTTP endpoints |
| gRPC API | grpcio (async) | RPC endpoints |
| Short-term storage | DragonflyDB | Events (Streams), State (Hashes) |
| Long-term storage | FalkorDB | Graph nodes, vector search, relationships |
| Embeddings | Qwen3-Embedding-8B | 4096-dim vectors via OpenRouter |
| LLM (free-form) | Grok 4.1 Fast | Reflection, synthesis, filtering, inference |
| LLM (structured) | DeepSeek v3.2 / Grok 4.1 Fast | DSPy-powered extraction with schema validation |
| Configuration | Dynaconf | TOML config + env overrides |
| Data validation | Pydantic v2 | Request/response schemas, DSPy output models |
| Python | 3.11+ | Async-first, type-annotated |

## License

MIT
