# Agent Memory Service — Architecture & Design

## Overview

**Segnog** (Agent Memory Service) is a general-purpose microservice for AI agent memory management. It implements a **dual-tier storage architecture** — short-term events in DragonflyDB, long-term episodes/knowledge/artifacts in FalkorDB — with an LLM-powered curation pipeline that distills raw observations into structured wisdom.

The service exposes dual APIs (gRPC + REST), manages multi-tenant scopes via `group_id`/`workflow_id`, and runs a background consolidation worker (REM Worker) for offline memory optimization.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Agent Memory Service                        │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────────────────┐  │
│  │ REST API │  │ gRPC API │  │       REM Background Worker      │  │
│  │ (FastAPI)│  │  (JSON)  │  │    (periodic consolidation)      │  │
│  └────┬─────┘  └────┬─────┘  └──────────────┬───────────────────┘  │
│       │              │                       │                      │
│       └──────┬───────┘                       │                      │
│              ▼                               │                      │
│  ┌───────────────────────┐                   │                      │
│  │ MemoryServiceHandler  │◄──────────────────┘                      │
│  │  (shared logic)       │                                          │
│  └───────────┬───────────┘                                          │
│              │                                                      │
│  ┌───────────┼────────────────────────────────────────────┐         │
│  │           ▼                                            │         │
│  │  ┌──────────────┐   ┌──────────────┐  ┌────────────┐  │         │
│  │  │ EpisodeStore │   │KnowledgeStore│  │ArtifactStore│  │         │
│  │  └──────┬───────┘   └──────┬───────┘  └─────┬──────┘  │         │
│  │         │                  │                 │         │         │
│  │         └──────────┬───────┘                 │         │         │
│  │                    ▼                         │         │         │
│  │            ┌──────────────┐                  │         │         │
│  │            │  BaseStore   │◄─────────────────┘         │         │
│  │            │ (_embed,     │                             │         │
│  │            │  _parse)     │                             │         │
│  │            └──────────────┘                             │         │
│  │                                                        │         │
│  │  ┌──────────────────┐    ┌─────────────────────────┐   │         │
│  │  │  DragonflyClient │    │   Smart Operations      │   │         │
│  │  │  (sessions,      │    │   (judge, reflect,      │   │         │
│  │  │   events, state) │    │    extract, synthesize)  │   │         │
│  │  └──────────────────┘    └─────────────────────────┘   │         │
│  └────────────────────────────────────────────────────────┘         │
│                                                                     │
│  ┌──────────────────┐  ┌────────────────────┐  ┌────────────────┐  │
│  │   DragonflyDB    │  │     FalkorDB       │  │   OpenRouter   │  │
│  │  (Redis, :6381)  │  │  (Graph DB, :6380) │  │  (LLM + Embed) │  │
│  └──────────────────┘  └────────────────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Module Organization

```
src/memory_service/
├── __init__.py                    # Package (version 0.1.0)
├── main.py                        # CLI entrypoint, async orchestration
├── config.py                      # Dynaconf settings management
│
├── core/                          # Framework-agnostic business logic
│   ├── __init__.py
│   └── observe.py                 # observe_core() — shared observe logic
│
├── storage/                       # Storage backends
│   ├── __init__.py                # init_backends() factory
│   ├── base_store.py              # BaseStore + normalize_name()
│   ├── dragonfly.py               # DragonflyClient (Redis/DragonflyDB)
│   ├── short_term.py              # ShortTermMemory (routing layer)
│   ├── episode_store.py           # EpisodeStore (FalkorDB)
│   ├── knowledge_store.py         # KnowledgeStore (FalkorDB)
│   └── artifact_store.py          # ArtifactStore (FalkorDB)
│
├── dto/                           # Pydantic data transfer objects
│   ├── events.py                  # Event DTOs
│   ├── episodes.py                # Episode + Observe DTOs
│   ├── knowledge.py               # Knowledge DTOs
│   ├── artifacts.py               # Artifact DTOs
│   ├── state.py                   # Execution state DTOs
│   └── pipelines.py               # Pipeline DTOs
│
├── llm/                           # LLM integration
│   ├── client.py                  # AsyncOpenAI wrapper (llm_call)
│   └── dspy_adapter.py            # DSPy LM config + DirectJSONAdapter
│
├── dspy_signatures/               # DSPy structured extraction schemas
│   ├── observation_signature.py   # ObservationJudgeSignature
│   ├── entity_signature.py        # EntityExtractionSignature
│   ├── knowledge_signature.py     # KnowledgeExtractionSignature
│   └── artifact_signature.py      # ArtifactExtractionSignature
│
├── smart/                         # LLM-powered operations
│   ├── judge_observation.py       # Observation → type/tier/labels
│   ├── reinterpret.py             # Task → labels/query/complexity
│   ├── filter.py                  # Filter results by relevance
│   ├── infer_state.py             # Infer state from memories
│   ├── synthesize.py              # Synthesize narrative briefing
│   ├── reflect.py                 # Generate reflection
│   ├── extract_knowledge.py       # Extract knowledge entries
│   ├── extract_artifacts.py       # Extract artifact entries
│   └── compress.py                # Compress events into episode
│
├── rest/                          # FastAPI REST server
│   ├── app.py                     # create_app() factory
│   ├── dependencies.py            # DI helpers (setup/teardown/getters)
│   └── routers/
│       ├── events.py              # /events endpoints
│       ├── episodes.py            # /episodes endpoints
│       ├── knowledge.py           # /knowledge endpoints
│       ├── artifacts.py           # /artifacts endpoints
│       ├── state.py               # /state endpoints
│       ├── smart.py               # /smart/* endpoints
│       ├── pipelines.py           # /pipelines endpoints
│       └── observe.py             # /observe endpoint
│
├── grpc/                          # gRPC server
│   ├── server.py                  # GenericServicer (JSON-over-gRPC)
│   └── service_handler.py         # MemoryServiceHandler
│
└── background/                    # Background workers
    └── rem_worker.py              # REMWorker (periodic consolidation)

proto/memory/v1/                   # Protocol Buffer definitions
├── common.proto                   # Scope, Pagination, Metadata
├── events.proto                   # EventsService
├── episodes.proto                 # EpisodesService
├── knowledge.proto                # KnowledgeService
├── artifacts.proto                # ArtifactsService
├── state.proto                    # StateService
├── smart.proto                    # SmartService
└── pipelines.proto                # PipelinesService
```

---

## Storage Architecture

### Dual-Tier Design

| Tier | Technology | Purpose | Latency | Data Types |
|------|-----------|---------|---------|------------|
| **Short-term** | DragonflyDB (Redis) | Real-time events, state, sessions | <1ms | Events, execution state, session embeddings |
| **Long-term** | FalkorDB (Graph DB) | Persistent memory with vector + graph search | ~50ms | Episodes, knowledge, artifacts |

### BaseStore Inheritance

All FalkorDB stores inherit from `BaseStore`, which provides:

```python
class BaseStore:
    def __init__(self, graph, openai_client, embedding_model, group_id="default")
    async def _embed(self, text: str) -> List[float]           # Single embedding
    async def _embed_batch(self, texts: List[str]) -> List[...]  # Batch embedding
    def _parse_results(self, result, json_columns=("labels",))   # Parse FalkorDB rows
```

`normalize_name(raw)` is a module-level function for deduplicating entity/label names (lowercase, hyphenated, alphanumeric only).

### DragonflyClient

Redis-compatible client for short-term storage:

| Operation | Key Pattern | Purpose |
|-----------|-------------|---------|
| `log_event()` | `events:{group_id}:{workflow_id}` | Redis Stream append |
| `get_recent_events()` | `events:{group_id}:{workflow_id}` | XREVRANGE |
| `hset()/hgetall()` | Custom keys | Execution state, tool stats |
| `session_add()` | `session:{session_id}` | Hash field per entry (JSON + embedding) |
| `session_search()` | `session:{session_id}` | Cosine similarity in Python (numpy) |
| `session_count()` | `session:{session_id}` | HLEN |
| `session_has()` | `session:{session_id}` | HEXISTS |

Sessions have a configurable TTL (default 3600s).

### EpisodeStore

Stores temporal episodes as FalkorDB `Episode` nodes with vector embeddings:

```
(Episode) {
  uuid, group_id, content, episode_type,
  consolidation_status, metadata (JSON),
  created_at, embedding (vecf32)
}
```

**Episode types**: `raw`, `reflection`, `compressed`, `narrative`
**Consolidation status**: `pending`, `consolidated`

**Graph edges**:
- `(ep1)-[:FOLLOWS {time_delta_seconds}]->(ep2)` — temporal chain
- `(reflection)-[:DERIVED_FROM]->(source)` — provenance

**Search capabilities**:
- Vector similarity (cosine distance via FalkorDB)
- Graph expansion (FOLLOWS/DERIVED_FROM edges, configurable hops)
- Entity search (proper noun matching)

### KnowledgeStore

Stores distilled knowledge with vector + label hybrid search:

```
(Knowledge) {
  uuid, group_id, content, knowledge_type,
  labels (JSON), confidence, source_mission,
  created_at, embedding (vecf32)
}
```

**Knowledge types**: `fact`, `pattern`, `insight`

**Graph edges**:
- `(knowledge)-[:HAS_LABEL]->(Label {name})` — label graph
- `(knowledge)-[:DERIVED_FROM]->(episode)` — provenance

**Hybrid search scoring**:
```
final_score = vector_score + 0.15 * (matching_labels / total_labels)
```

### ArtifactStore

Stores artifact references (files, reports, code, URLs):

```
(Artifact) {
  uuid, group_id, name, artifact_type, path,
  description, labels (JSON), source_mission,
  created_at, embedding (vecf32)
}
```

**Artifact types**: `file`, `report`, `dataset`, `code`, `url`

Same hybrid search and label graph as KnowledgeStore.

---

## Data Flows

### 1. Observe Flow (Hot Path)

The primary ingestion endpoint, optimized for latency:

```
Client → POST /observe {session_id, content, timestamp, source, metadata}
           │
           ▼
     observe_core()
           │
           ├─ 1. Embed content (~200ms)
           │      episode_store._embed(content) → OpenRouter API
           │
           ├─ 2. Store in DragonflyDB session (<1ms)
           │      dragonfly.session_add(session_id, uuid, content, embedding)
           │
           ├─ 3. Cold start check
           │      session_count < 2?
           │
           ├─ YES (Cold Start):
           │      ├─ FalkorDB vector search (episodes) ──┐
           │      ├─ FalkorDB hybrid search (knowledge)──┤ parallel
           │      └─ Entity enrichment                   ─┘
           │      Return FalkorDB results
           │
           ├─ NO (Warm Session):
           │      └─ DragonflyDB session search (cosine, numpy)
           │         Return session results
           │
           └─ 4. Fire background hydration (async, non-blocking)
                  asyncio.create_task(background_hydrate(...))
           │
           ▼
     Return {episode_uuid, observation_type, context: {episodes, knowledge}}
```

**Background hydration** (runs after response is sent):
1. Store episode in FalkorDB (long-term persistence)
2. Search FalkorDB for related episodes + knowledge (parallel)
3. Entity enrichment (proper noun extraction + search)
4. Hydrate session: add top 15 episodes + 10 knowledge entries to DragonflyDB
5. Run judge: classify observation via DSPy (type, tier, importance, labels)

### 2. Startup Pipeline (7 Steps)

Called when an agent starts a new task — retrieves full context:

```
StartupPipeline(task, scope)
  │
  ├─ Step 0: Reinterpret task (DSPy)
  │    → search_labels[], search_query, complexity
  │
  ├─ Step 1: Episode vector search
  │    episode_store.search_episodes(search_query)
  │
  ├─ Step 2: Knowledge + artifact search (parallel)
  │    ├─ knowledge_store.search_hybrid(query, labels)
  │    └─ artifact_store.search_hybrid(query, labels)
  │
  ├─ Step 3: LLM filter on episodes
  │    filter_memory_results(task, results, max=5)
  │
  ├─ Step 4: Tool statistics
  │    get_tool_stats() from DragonflyDB
  │
  ├─ Step 5: State inference (LLM)
  │    infer_state(task, memories)
  │
  └─ Step 6: Background narrative synthesis (LLM)
       synthesize_background(all_context)
       → narrative text for agent prompt injection
```

### 3. REM/Curation Flow (Background Worker)

Periodic consolidation of raw episodes into structured wisdom:

```
REMWorker._run_cycle()
  │
  ├─ Find pending groups:
  │    MATCH (e:Episode) WHERE consolidation_status='pending'
  │    GROUP BY group_id, score by count + age
  │
  └─ For each group (up to batch_size=5):
       │
       ├─ Fetch pending raw episodes (limit 20)
       │
       ├─ Step 1: Generate reflection (LLM)
       │    → structured analysis of what happened
       │
       ├─ Step 2: Store reflection as Episode (type='reflection')
       │    Link to source episodes via DERIVED_FROM edges
       │    Extract and link entities
       │
       ├─ Step 3: Extract knowledge (DSPy)
       │    → [{content, type, labels, confidence}, ...]
       │
       ├─ Step 4: Store knowledge entries
       │    Create Knowledge nodes + HAS_LABEL edges + DERIVED_FROM edges
       │
       ├─ Step 5: Extract artifacts (DSPy)
       │    → [{name, type, path, description, labels}, ...]
       │
       ├─ Step 6: Store artifact entries
       │
       └─ Step 7: Mark source episodes as consolidated
            SET consolidation_status = 'consolidated'
```

### 4. Store/Search Patterns

**Episode Write Path**:
```
store_episode(content, metadata, episode_type='raw')
  → _embed(content) → CREATE Episode node
  → _auto_link_to_predecessor() → CREATE FOLLOWS edge
```

**Knowledge Write Path**:
```
store_knowledge(entries[], source_mission)
  → _embed_batch(contents) → CREATE Knowledge nodes
  → MERGE Label nodes → CREATE HAS_LABEL edges
  → CREATE DERIVED_FROM edge to source episode
```

**Vector Search** (all stores):
```
MATCH (n:NodeType)
WHERE n.group_id = $group_id
WITH n, (2 - vec.cosineDistance(n.embedding, vecf32($query))) / 2 AS score
WHERE score > $min_score
ORDER BY score DESC LIMIT $top_k
```

**Graph Expansion** (episodes):
```
OPTIONAL MATCH (center)-[:FOLLOWS*1..N]->(fwd)
OPTIONAL MATCH (bwd)-[:FOLLOWS*1..N]->(center)
OPTIONAL MATCH (center)-[:DERIVED_FROM*1..N]->(derived)
→ discount 0.9x for expanded results
```

---

## Multi-Tenant Scoping

Every operation is scoped by two dimensions:

| Dimension | Purpose | Applied To |
|-----------|---------|-----------|
| `group_id` | Tenant/project isolation | FalkorDB queries (WHERE group_id=), DragonflyDB stream keys |
| `workflow_id` | Workflow instance isolation | DragonflyDB stream keys (events:{group_id}:{workflow_id}) |

In gRPC, scope is extracted by `_apply_scope(req, *stores)`:
```python
def _apply_scope(self, req, *stores):
    scope = req.get("scope", {})
    group_id = scope.get("group_id", "default")
    workflow_id = scope.get("workflow_id", "default")
    self._dragonfly.set_scope(group_id, workflow_id)
    for store in stores:
        store._group_id = group_id
    return group_id, workflow_id
```

In REST, the observe endpoint maps `session_id` directly to `group_id`.

---

## LLM Integration

### Embedding Pipeline

| Setting | Value |
|---------|-------|
| Model | `qwen/qwen3-embedding-8b:nitro` |
| Provider | OpenRouter (OpenAI-compatible API) |
| Encoding | `float` |
| Latency | ~200ms per call |

Used via `BaseStore._embed()` and `_embed_batch()` for all vector operations.

### DSPy Structured Extraction

For operations requiring structured output (knowledge extraction, observation judging, entity extraction, artifact extraction):

| Component | Purpose |
|-----------|---------|
| `DirectJSONAdapter` | Custom DSPy adapter that uses `json_object` response format |
| `dspy.Predict` | Runs signatures through configured LM |
| Default model | `arcee-ai/trinity-mini` via OpenRouter |

**Signatures**:
- `ObservationJudgeSignature` → `ObservationAnalysis` (type, tier, labels, importance)
- `EntityExtractionSignature` → `EntityExtractionResult` (entities list)
- `KnowledgeExtractionSignature` → knowledge entries list
- `ArtifactExtractionSignature` → artifact entries list

### Free-form LLM Calls

For operations requiring narrative output (reflection, synthesis, filtering, state inference):

| Setting | Value |
|---------|-------|
| Model | `arcee-ai/trinity-mini` |
| Provider | OpenRouter |
| Client | `AsyncOpenAI` via `llm_call()` helper |

---

## API Reference

### REST Endpoints (FastAPI)

**Base URL**: `/api/v1/memory`

| Category | Endpoint | Method | Purpose |
|----------|----------|--------|---------|
| Health | `/health` | GET | Health check |
| **Observe** | `/observe` | POST | Short-term first observation (hot path) |
| Events | `/events` | POST | Log event |
| Events | `/events/recent` | GET | Get recent events |
| Events | `/events/search` | POST | Search events |
| Episodes | `/episodes` | POST | Store episode |
| Episodes | `/episodes/search` | POST | Vector search episodes |
| Episodes | `/episodes/search/entities` | POST | Entity-based search |
| Episodes | `/episodes/link` | POST | Link episodes |
| Knowledge | `/knowledge` | POST | Store knowledge entries |
| Knowledge | `/knowledge/search` | POST | Hybrid search (vector + labels) |
| Knowledge | `/knowledge/search-labels` | POST | Label-only search |
| Artifacts | `/artifacts` | POST | Store artifacts |
| Artifacts | `/artifacts/search` | POST | Hybrid search |
| Artifacts | `/artifacts/{uuid}` | GET | Get artifact by UUID |
| Artifacts | `/artifacts/recent/list` | GET | List recent artifacts |
| Artifacts | `/artifacts/{uuid}` | DELETE | Delete artifact |
| State | `/state/persist` | POST | Persist execution state |
| State | `/state/current` | GET | Get current state |
| State | `/state/tool-stats` | POST | Update tool stats |
| State | `/state/tool-stats` | GET | Get tool stats |
| State | `/state/memory-context` | GET | Get composite context |
| Smart | `/smart/reinterpret` | POST | Task reinterpretation |
| Smart | `/smart/filter` | POST | Filter results |
| Smart | `/smart/infer-state` | POST | Infer state |
| Smart | `/smart/synthesize` | POST | Synthesize narrative |
| Smart | `/smart/reflect` | POST | Generate reflection |
| Smart | `/smart/extract-knowledge` | POST | Extract knowledge |
| Smart | `/smart/extract-artifacts` | POST | Extract artifacts |
| Smart | `/smart/compress` | POST | Compress events |
| Pipelines | `/pipelines/startup` | POST | Full startup pipeline |
| Pipelines | `/pipelines/curation` | POST | Full curation pipeline |

### gRPC Service (JSON-over-gRPC)

**Service**: `memory.v1.MemoryService`

Uses a **generic JSON-over-gRPC transport** — proto files define the contract for documentation and client generation, but the server uses JSON serialization instead of compiled protobuf stubs.

30+ RPC methods mapped to `MemoryServiceHandler` methods:
```
/memory.v1.MemoryService/LogEvent         → handler.log_event()
/memory.v1.MemoryService/StoreEpisode     → handler.store_episode()
/memory.v1.MemoryService/SearchEpisodes   → handler.search_episodes()
/memory.v1.MemoryService/StoreKnowledge   → handler.store_knowledge()
/memory.v1.MemoryService/SearchKnowledge  → handler.search_knowledge()
/memory.v1.MemoryService/Observe          → handler.observe()
/memory.v1.MemoryService/StartupPipeline  → handler.startup_pipeline()
/memory.v1.MemoryService/RunCuration      → handler.run_curation()
...
```

---

## FalkorDB Graph Schema

### Nodes

```
(:Episode {
    uuid: STRING,          # Unique identifier
    group_id: STRING,      # Tenant scope
    content: STRING,       # Raw text content
    episode_type: STRING,  # raw | reflection | compressed | narrative
    consolidation_status: STRING,  # pending | consolidated
    metadata: STRING,      # JSON-encoded metadata
    created_at: FLOAT,     # Unix epoch
    created_at_iso: STRING,# ISO 8601 timestamp
    embedding: VECF32      # Vector embedding
})

(:Knowledge {
    uuid: STRING,
    group_id: STRING,
    content: STRING,
    knowledge_type: STRING,  # fact | pattern | insight
    labels: STRING,          # JSON array of label strings
    confidence: FLOAT,       # 0.0-1.0
    source_mission: STRING,  # Originating task (truncated 200 chars)
    mission_status: STRING,  # success | max_iterations
    source_episode_uuid: STRING,
    created_at: FLOAT,
    embedding: VECF32
})

(:Artifact {
    uuid: STRING,
    group_id: STRING,
    name: STRING,
    artifact_type: STRING,  # file | report | dataset | code | url
    path: STRING,
    description: STRING,
    labels: STRING,          # JSON array
    source_mission: STRING,
    mission_status: STRING,
    source_episode_uuid: STRING,
    created_at: FLOAT,
    embedding: VECF32
})

(:Entity {
    name: STRING,
    entity_type: STRING  # person | organization | place | product | other
})

(:Label {
    name: STRING  # Normalized (lowercase, hyphenated)
})
```

### Edges

```
(:Episode)-[:FOLLOWS {time_delta_seconds: FLOAT}]->(:Episode)
(:Episode)-[:DERIVED_FROM]->(:Episode)
(:Knowledge)-[:DERIVED_FROM]->(:Episode)
(:Artifact)-[:DERIVED_FROM]->(:Episode)
(:Knowledge)-[:HAS_LABEL]->(:Label)
(:Artifact)-[:HAS_LABEL]->(:Label)
(:Episode)-[:HAS_ENTITY]->(:Entity)
```

### Indexes

```
Episode:  uuid, group_id, episode_type, created_at, consolidation_status
Knowledge: uuid, group_id, knowledge_type, created_at
Artifact: uuid, group_id, artifact_type, created_at
Entity:  name, entity_type
Label:   name
```

---

## Configuration

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
default_group_id = "framework"
default_workflow_id = "default"

[default.falkordb]
url = "redis://localhost:6380"
graph_name = "episode_store"

[default.embeddings]
model = "qwen/qwen3-embedding-8b:nitro"
base_url = "https://openrouter.ai/api/v1"

[default.llm]
flash_model = "arcee-ai/trinity-mini"
base_url = "https://openrouter.ai/api/v1"

[default.dspy]
models = ["arcee-ai/trinity-mini"]

[default.session]
ttl_seconds = 3600
hydration_enabled = true
cold_start_sync = true

[default.background]
enabled = true
interval_seconds = 60
batch_size = 5
min_episodes_for_processing = 3
```

### Environment Variable Overrides

Prefix: `MEMORY_SERVICE_`, double underscore for nesting:

| Variable | Purpose |
|----------|---------|
| `MEMORY_SERVICE_DRAGONFLY__URL` | DragonflyDB connection |
| `MEMORY_SERVICE_FALKORDB__URL` | FalkorDB connection |
| `MEMORY_SERVICE_EMBEDDINGS__API_KEY` | Embedding API key |
| `MEMORY_SERVICE_EMBEDDINGS__MODEL` | Embedding model override |
| `MEMORY_SERVICE_LLM__API_KEY` | LLM API key |
| `MEMORY_SERVICE_LLM__FLASH_MODEL` | LLM model override |

---

## Deployment

### Docker Architecture

Single container bundles all three services via supervisord:

```
┌─────────────────────────────────────────┐
│            Docker Container             │
│                                         │
│  ┌──────────────────────────────────┐   │
│  │          supervisord             │   │
│  │                                  │   │
│  │  ┌────────────┐ ┌────────────┐  │   │
│  │  │ DragonflyDB│ │  FalkorDB  │  │   │
│  │  │   :6381    │ │   :6380    │  │   │
│  │  └────────────┘ └────────────┘  │   │
│  │  ┌────────────────────────────┐ │   │
│  │  │    Memory Service          │ │   │
│  │  │  gRPC :50051 + REST :9000  │ │   │
│  │  └────────────────────────────┘ │   │
│  └──────────────────────────────────┘   │
│                                         │
│  Volumes:                               │
│    /data/dragonfly  (persistence)       │
│    /data/falkordb   (persistence)       │
│                                         │
│  Ports:                                 │
│    50051 → gRPC                         │
│    9000  → REST                         │
└─────────────────────────────────────────┘
```

### docker-compose.yml

```yaml
services:
  segnog:
    build: .
    ports:
      - "50051:50051"
      - "9000:9000"
    environment:
      - MEMORY_SERVICE_EMBEDDINGS__API_KEY=${OPENROUTER_API_KEY}
      - MEMORY_SERVICE_LLM__API_KEY=${OPENROUTER_API_KEY}
    volumes:
      - dragonfly_data:/data/dragonfly
      - falkordb_data:/data/falkordb
    restart: unless-stopped
```

### Health Check

```
GET http://localhost:9000/health → {"status": "ok", "service": "agent-memory-service"}
```

---

## Startup Sequence

```
cli() → asyncio.run(main())
  │
  ├─ init_backends(session_ttl)
  │    ├─ DragonflyClient.connect()
  │    ├─ FalkorDB graph selection
  │    ├─ AsyncOpenAI client creation
  │    ├─ EpisodeStore.ensure_indexes()
  │    ├─ KnowledgeStore.ensure_indexes()
  │    └─ ArtifactStore.ensure_indexes()
  │
  ├─ MemoryServiceHandler(all backends)
  │
  └─ asyncio.gather(
       run_grpc_server(handler, 50051),
       run_rest_server("0.0.0.0", 9000),
       rem_worker.run()  # if background.enabled
     )
```

---

## Dependencies

| Category | Package | Version | Purpose |
|----------|---------|---------|---------|
| REST | fastapi | ≥0.115.0 | HTTP API framework |
| REST | uvicorn[standard] | ≥0.30.0 | ASGI server |
| gRPC | grpcio | ≥1.68.0 | gRPC core |
| gRPC | grpcio-reflection | ≥1.68.0 | Service reflection |
| gRPC | protobuf | ≥5.28.0 | Protocol buffers |
| Storage | redis[hiredis] | ≥5.0.0 | DragonflyDB client |
| Storage | falkordb | ≥1.0.0 | FalkorDB graph client |
| LLM | openai | ≥1.50.0 | Embeddings + LLM calls |
| LLM | dspy | ≥2.5.0 | Structured extraction |
| Config | dynaconf | ≥3.2.0 | Settings management |
| Utilities | numpy | ≥1.26.0 | Cosine similarity |
| Utilities | pydantic | ≥2.9.0 | Data validation |
| Utilities | httpx | ≥0.27.0 | HTTP client |

---

## Key Design Decisions

1. **Short-term first architecture**: DragonflyDB session as primary store for observe, FalkorDB as background hydration target. Returns in <300ms vs >500ms for synchronous FalkorDB.

2. **JSON-over-gRPC**: Proto files define the contract, but the server uses JSON serialization for implementation simplicity. Proto definitions serve as documentation and client code generation.

3. **Shared handler pattern**: `MemoryServiceHandler` implements all business logic once. Both gRPC `GenericServicer` and FastAPI routers delegate to it.

4. **BaseStore inheritance**: Eliminates duplicate embedding, parsing, and initialization code across three FalkorDB store classes.

5. **REM Worker metaphor**: Background consolidation cycle named after REM sleep — processes raw memories into structured knowledge during "downtime".

6. **Hybrid search scoring**: Knowledge and artifact search combines vector similarity with label graph matching (`final = vector + 0.15 * label_ratio`).

7. **Entity enrichment**: Proper noun extraction via regex supplements vector search, with merge scoring that boosts overlapping results (+0.1) and discounts entity-only results (0.7x).

8. **Bundled container**: All services (DragonflyDB, FalkorDB, Python service) in one container via supervisord for simple deployment.
