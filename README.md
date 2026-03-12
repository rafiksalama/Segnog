# Segnog

> **Dal Segno** — *from the sign*. In music, the performer returns to the segno mark and replays the passage with everything they have learned. The second time through is never the same as the first.

Segnog is a memory microservice for AI agents. It stores what happened, distills what mattered, and returns the right context at exactly the right moment — so the agent returns to the sign and plays it better.

---

## What It Does

An AI agent calls `observe` with its current observation. Segnog automatically:

1. **Stores** the observation in short-term session memory (DragonflyDB)
2. **Retrieves** related episodes and knowledge from long-term memory (FalkorDB) using 3D scoring (semantic + temporal + Hebbian)
3. **Summarizes** the session context via LLM into a concise, relevant passage
4. **Returns** that context so the agent can act immediately
5. **Consolidates** in the background — stores to the graph, reinforces Hebbian associations, judges importance, and extracts structured knowledge

All of this happens through a single endpoint.

---

## Architecture

```
                        Agent Framework (caller)
                                  │
                    ┌─────────────┴──────────────┐
                    │                            │
              gRPC :50051                  REST :9000
              (JSON-over-gRPC)             (FastAPI)
                    │                            │
                    └─────────────┬──────────────┘
                                  │
                       MemoryServiceHandler
                       (shared business logic)
                                  │
         ┌──────────┬─────────────┼─────────────┬──────────────┐
         │          │             │             │              │
    DragonflyDB  FalkorDB       NATS        OpenAI          DSPy
    (short-term) (long-term)  (event bus)  (embeddings    (structured
     Redis        Graph DB    JetStream     + LLM calls)   extraction)
    :6381         :6380        :4222
         │          │
    Session     Episodes
    Cache       Knowledge
    Events      Artifacts
                Entities
                Hebbian Graph
                    │
         ┌──────────┴──────────┐
         │                     │
   CurationWorker        REMSweepWorker
   (NATS subscriber      (background
    or polling)           consolidation)
```

All six services — DragonflyDB, FalkorDB, NATS, gRPC server, REST server, and background workers — run in a single Docker container managed by supervisord.

---

## Core Concepts

### Episodes

An episode is a single observation or experience: a raw conversation turn, a tool call result, a mission trace. Episodes are the atomic unit of memory.

Every episode is stored with:
- A vector embedding for semantic retrieval
- Metadata (timestamp, source, group scope)
- A consolidation status: `pending` → `consolidated` (or `duplicate`)
- An activation count that grows with retrieval (Hebbian)

**Lifecycle:** `observe` → DragonflyDB (hot) → FalkorDB (background) → REM consolidation → knowledge extraction

### Knowledge

Knowledge is extracted from episodes by LLM during the REM cycle. It represents distilled facts, patterns, and insights — things the agent has learned across many missions.

Each knowledge entry has a type (`fact`, `pattern`, `insight`, `procedure`), semantic labels, a confidence score, and is linked back to its source episode via a `DERIVED_FROM` edge.

Knowledge is deduplicated at write time: entries with >0.90 cosine similarity to existing knowledge are dropped; instead, a `REINFORCES` edge is added to strengthen the existing entry.

### Sessions (Short-Term Memory)

A session is a scoped cache in DragonflyDB keyed by `session_id`. It holds:
- **Local entries**: the raw observations added in this session
- **Hydrated episodes**: related episodes pulled from FalkorDB during cold start or background hydration
- **Hydrated knowledge**: relevant knowledge entries pulled from FalkorDB

Sessions expire by TTL (default 24 hours). They are the fast path — when a session is warm, context generation is a single LLM call over cached data.

### The Observe Endpoint

`observe` is the single entry point for all memory operations. It handles routing, retrieval, summarization, and background consolidation automatically.

**Cold start** (session entry count < 2):
1. Reinterpret the content for optimized FalkorDB search (DSPy)
2. Search FalkorDB: vector similarity + entity search, scored in 3D
3. Pre-fill the session cache with the top relevant episodes and knowledge
4. LLM summarize the session → return context

**Warm path** (session already populated):
1. Read session entries from DragonflyDB (capped at 100 most recent)
2. If `read_only`, also search FalkorDB knowledge live for the question
3. LLM summarize → return context

In both cases, background tasks fire-and-forget to store in FalkorDB, reinforce Hebbian associations, and judge observation importance.

**Read-only mode** (`read_only: true`): skips all writes. Useful for evaluation and read-only agents.

---

## 3D Scoring

Every retrieval result is scored on three dimensions before being returned to the agent.

### Dimension 1 — Semantic

Cosine similarity between the query embedding and the episode embedding, computed by FalkorDB's vector index.

### Dimension 2 — Temporal (Recency)

Freshness decays hyperbolically over time:

```
freshness = 1 / (1 + age_hours / half_life_hours)
```

Configurable half-lives per store tier:
- **Session**: 0.5 hours (strong recency bias)
- **Episodes**: 168 hours / 1 week
- **Knowledge**: 720 hours / 30 days

### Dimension 3 — Hebbian (Co-activation)

Episodes that have been retrieved together repeatedly develop stronger associative links — "neurons that fire together, wire together."

```
hebbian_boost = 0.5 × activation_strength + 0.5 × co_activation_weight
activation_strength = log(1 + count) / log(1 + activation_cap)
```

Co-activation weights grow asymptotically with each co-retrieval:
```
new_weight = old_weight + lr × (1 − old_weight)
```

This means frequently co-retrieved episodes surface together over time, without ever exceeding 1.0.

### Final Score

```
score = (1 − α − β) × semantic + α × freshness + β × hebbian

Defaults:  α = 0.3 (temporal),  β = 0.2 (Hebbian)
```

---

## Background Consolidation (REM)

Inspired by biological REM sleep, the REM worker runs periodic cycles to consolidate short-term experiences into long-term structured knowledge.

### Cycle

1. **Discovery**: Find groups with ≥3 pending raw episodes, prioritized by volume × age
2. **Deduplication**: Compare each pending episode against consolidated ones
   - ≥0.90 similarity → mark `DUPLICATE_OF`, skip curation
   - <0.90 → include in curation batch
3. **Curation**: DSPy pipeline extracts knowledge, artifacts, and a reflection narrative from the unique episode batch
4. **Storage**: Knowledge stored to FalkorDB with deduplication and label linking
5. **Consolidation**: Source episodes marked `consolidated`
6. **Compression**: Unique episodes compressed into a summary episode
7. **Hebbian Decay**: Stale `CO_ACTIVATED` edge weights decayed; edges below 0.01 pruned

### Modes

**Polling** (default): REMWorker polls on a configurable interval (default 60s).

**Event-driven** (NATS): CurationWorker subscribes to `memory.episodes.created` events, batches episodes, and triggers consolidation. Lower latency, no polling overhead.

---

## Storage Backends

### DragonflyDB — Short-Term Memory (`:6381`)

Redis-compatible in-memory store with snapshot persistence (`--snapshot_cron "* * * * *"`).

- **Session hashes**: per-session caches with TTL
- **Event streams**: Redis Streams for observation logging scoped by `group_id:workflow_id`
- **Semantic search within session**: cosine similarity computed in Python over session entries

### FalkorDB — Long-Term Memory (`:6380`)

Property graph database. All data persisted to RDB snapshot.

**Node types:**
| Node | Purpose |
|------|---------|
| `Episode` | Raw + consolidated observations with embeddings |
| `Knowledge` | Extracted facts, patterns, insights |
| `Artifact` | Generated files, tools, summaries |
| `Entity` | Named entities, people, organizations |
| `Label` | Semantic tags (deduplicated via MERGE) |

**Edge types:**
| Edge | Purpose |
|------|---------|
| `FOLLOWS` | Sequential ordering within a group |
| `DUPLICATE_OF` | Deduplication link (REM) |
| `CO_ACTIVATED` | Hebbian co-occurrence (weight, count, timestamps) |
| `DERIVED_FROM` | Knowledge → source Episode |
| `REINFORCES` | Strengthened knowledge link on dedup |
| `HAS_LABEL` | Knowledge ↔ Label |

**Vector search**: Cosine distance index on `vecf32` embeddings.

### NATS JetStream (`:4222`)

Optional event bus for event-driven curation. When enabled, replaces the polling REM worker with:
- `CurationWorker`: subscribes to `memory.episodes.created`, batches, curates
- `REMSweepWorker`: processes curation completion events, runs consolidation

---

## APIs

### REST (`:9000`)

All endpoints are under `/api/v1/memory/`.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/observe` | POST | Core observe — store, retrieve, summarize, return context |
| `/episodes` | POST | Direct episode storage |
| `/episodes/search` | POST | Semantic episode search with 3D scoring |
| `/episodes/search/entities` | POST | Search by named entity |
| `/episodes/link` | POST | Create explicit edge between episodes |
| `/knowledge` | POST | Store knowledge entries |
| `/knowledge/search` | POST | Hybrid knowledge search (vector + label) |
| `/artifacts` | POST | Store artifacts |
| `/artifacts/search` | POST | Search artifacts |
| `/events` | POST | Log custom events |
| `/events/recent` | GET | Retrieve recent events |
| `/pipelines/curation` | POST | Trigger curation manually |
| `/smart/reinterpret-task` | POST | Optimize a task query |
| `/smart/extract-knowledge` | POST | Extract knowledge from mission data |
| `/smart/synthesize-background` | POST | Synthesize background narrative |
| `/health` | GET | Health check |

### gRPC (`:50051`)

Mirror of the REST API over Protocol Buffers with JSON-over-gRPC support. Reflection enabled for client discovery.

### Observe Request

```json
{
  "session_id": "my-agent-session",
  "content": "User asked about last week's deployment.",
  "timestamp": "2025-05-01T14:30:00Z",
  "source": "chat",
  "metadata": {"user_id": "u123"},
  "read_only": false
}
```

### Observe Response

```json
{
  "episode_uuid": "550e8400-e29b-41d4-a716-446655440000",
  "observation_type": "chat",
  "context": "Last week you deployed v2.3 to staging on April 24th. The deployment had a memory leak in the worker pool that was patched in v2.3.1 the following day...",
  "search_labels": ["deployment", "infrastructure"],
  "search_query": "deployment events and incidents last week"
}
```

---

## DSPy Smart Operations

All LLM operations use DSPy structured signatures with configurable models via OpenRouter.

| Operation | Purpose |
|-----------|---------|
| `judge_observation` | Route observation type; assess importance |
| `reinterpret_task` | Optimize cold-start search query + labels |
| `summarize_context` | Synthesize session entries into coherent context |
| `extract_knowledge` | Mine facts, patterns, insights from mission data |
| `extract_artifacts` | Extract generated code, tools, documents |
| `extract_entities` | Extract named entities and relationships |
| `compress` | Temporal compression of episode sequences |
| `reflect` | Generate narrative reflection on what was learned |
| `synthesize` | Synthesize mission background narrative |
| `infer_state` | Infer agent state from execution trace |
| `filter` | Filter results for relevance |

---

## Configuration

Configured via `settings.toml` with optional `.secrets.toml` overrides (not committed).

```toml
[default.falkordb]
url = "redis://localhost:6380"
graph_name = "episode_store"

[default.dragonfly]
url = "redis://localhost:6381"

[default.embeddings]
model = "qwen/qwen3-embedding-8b:nitro"
base_url = "https://openrouter.ai/api/v1"

[default.llm]
flash_model = "x-ai/grok-4.1-fast"
base_url = "https://openrouter.ai/api/v1"

[default.session]
ttl_seconds = 86400          # 24 hours

[default.scoring]
episode_half_life_hours = 168.0    # 1 week
episode_alpha = 0.3                # temporal weight
knowledge_half_life_hours = 720.0  # 30 days
knowledge_alpha = 0.2

[default.hebbian]
enabled = true
learning_rate = 0.1
beta_episode = 0.2           # Hebbian weight in 3D score
activation_cap = 1000
decay_rate = 0.01
decay_interval_hours = 168

[default.background]
enabled = true
interval_seconds = 60        # REM cycle interval
batch_size = 5
min_episodes_for_processing = 3

[default.nats]
enabled = false              # Set true for event-driven mode
url = "nats://localhost:4222"
```

**Secrets** (in `.secrets.toml` or environment):

```toml
[default.embeddings]
api_key = "sk-or-v1-..."

[default.llm]
api_key = "sk-or-v1-..."
```

Or via environment variables:
```bash
MEMORY_SERVICE_EMBEDDINGS__API_KEY=sk-or-v1-...
MEMORY_SERVICE_LLM__API_KEY=sk-or-v1-...
```

---

## Deployment

### Docker (Recommended)

The Docker image bundles all six services (DragonflyDB, FalkorDB, NATS, gRPC, REST, workers) into a single container supervised by supervisord.

```bash
# Build
docker-compose build

# Start
docker-compose up -d

# Check health
curl http://localhost:9000/health
```

Named Docker volumes persist data across rebuilds:
- `dragonfly_data` — Session cache + event streams (snapshots every minute)
- `falkordb_data` — Long-term episodes, knowledge, artifacts
- `nats_data` — Event stream persistence

```yaml
# docker-compose.yml excerpt
services:
  segnog:
    build: .
    ports:
      - "50051:50051"   # gRPC
      - "9000:9000"     # REST
    environment:
      - MEMORY_SERVICE_EMBEDDINGS__API_KEY=${OPENROUTER_API_KEY}
      - MEMORY_SERVICE_LLM__API_KEY=${OPENROUTER_API_KEY}
    volumes:
      - dragonfly_data:/data/dragonfly
      - falkordb_data:/data/falkordb
      - nats_data:/data/nats
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:9000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### Local Development

```bash
pip install -e .

# Set secrets
cp .secrets.toml.example .secrets.toml
# Edit .secrets.toml with your OpenRouter API key

# Run (requires DragonflyDB, FalkorDB, NATS already running)
python -m memory_service.main
```

---

## Scoping

All data is scoped by `group_id` (and optionally `workflow_id`). This allows multiple independent agents or conversations to share the same service instance without data leakage.

- **group_id**: typically the agent ID, user ID, or conversation ID
- **workflow_id**: sub-scope within a group (e.g., a specific task or run)

All FalkorDB queries filter by `group_id`. All session keys include `group_id`. All NATS events carry `group_id` metadata.

---

## Benchmark — LoCoMo

The repository includes a LoCoMo (Long Conversation Modeling) benchmark to evaluate retrieval quality.

### Running

```bash
# Ingestion phase — ingest conversation into memory service
python -m benchmarks.locomo run --phase ingest --conversations 0

# Evaluation phase — QA evaluation with F1 + LLM-as-judge scoring
python -m benchmarks.locomo run --phase evaluate --conversations 0 \
    --retrieval observe --rate-limit 2 --use-llm-judge
```

### Retrieval Modes

| Mode | Description |
|------|-------------|
| `observe` | Full observe pipeline (warm path + knowledge search) |
| `episodes_only` | Direct FalkorDB episode search |
| `episodes_knowledge` | Episode + knowledge search combined |
| `full_pipeline` | Startup pipeline (background narrative + context) |

### Scoring

| Metric | Description |
|--------|-------------|
| F1 | Token overlap between predicted and ground-truth answer |
| LLM Judge | Binary CORRECT/WRONG by a separate LLM evaluator |

Results are saved per-run to `benchmarks/locomo/results/` with full per-question breakdowns.

### QA Categories

| Category | Description |
|----------|-------------|
| 1. Single-hop | Direct factual recall |
| 2. Temporal | Date and sequence reasoning |
| 3. Multi-hop | Cross-session inference |
| 4. Open-domain | General knowledge + conversation context |
| 5. Adversarial | Questions about facts not in the conversation |

---

## File Structure

```
agent-memory-service/
│
├── Dockerfile                          # All-in-one container
├── docker-compose.yml
├── settings.toml                       # Service configuration
├── .secrets.toml                       # API keys (git-ignored)
│
├── src/memory_service/
│   ├── main.py                         # CLI entry point
│   ├── config.py                       # Dynaconf settings
│   │
│   ├── core/
│   │   ├── observe.py                  # observe_core() — hot path
│   │   └── hebbian.py                  # Co-activation reinforcement
│   │
│   ├── storage/
│   │   ├── dragonfly.py                # DragonflyDB client (sessions + events)
│   │   ├── episode_store.py            # FalkorDB episodes
│   │   ├── knowledge_store.py          # FalkorDB knowledge
│   │   └── artifact_store.py           # FalkorDB artifacts
│   │
│   ├── scoring.py                      # 2D and 3D scoring functions
│   │
│   ├── smart/                          # DSPy-powered LLM operations
│   │   ├── summarize_context.py
│   │   ├── reinterpret.py
│   │   ├── extract_knowledge.py
│   │   ├── judge_observation.py
│   │   └── ...
│   │
│   ├── dspy_signatures/                # DSPy prompt signatures
│   │
│   ├── rest/                           # FastAPI REST server
│   │   ├── app.py
│   │   └── routers/
│   │       ├── observe.py
│   │       ├── episodes.py
│   │       ├── knowledge.py
│   │       └── ...
│   │
│   ├── grpc/                           # gRPC server
│   │   ├── server.py
│   │   └── service_handler.py
│   │
│   ├── events/                         # NATS event-driven workers
│   │   ├── curation_worker.py
│   │   └── rem_sweep_worker.py
│   │
│   ├── background/
│   │   └── rem_worker.py               # Polling-based REM consolidation
│   │
│   └── dto/                            # Pydantic request/response models
│
├── benchmarks/locomo/                  # LoCoMo benchmark suite
│   ├── runner.py
│   ├── ingest.py
│   ├── retrieve.py
│   ├── answer.py
│   ├── score.py
│   └── segnog_client.py
│
├── proto/                              # Protocol Buffer definitions
└── tests/
```

---

## Initialization Sequence

```
python -m memory_service.main
  │
  ├── Connect DragonflyDB (redis.asyncio)
  ├── Connect FalkorDB (select_graph "episode_store")
  ├── Connect OpenAI client (OpenRouter)
  ├── Init EpisodeStore + KnowledgeStore + ArtifactStore
  │     └── ensure_indexes() — create vector/property indexes
  ├── Connect NATS (if enabled)
  │
  ├── Start gRPC server :50051
  ├── Start REST server :9000
  │
  ├── IF NATS enabled:
  │     ├── CurationWorker.run()
  │     ├── REMSweepPublisher.run()
  │     └── REMSweepWorker.run()
  └── ELSE:
        └── REMWorker.run()   ← polling every 60s
```

---

## Design Decisions

**Why DragonflyDB + FalkorDB?**
Two storage tiers with different access patterns. DragonflyDB is the hot cache — sub-millisecond reads, TTL-based expiry, Redis-compatible. FalkorDB is the cold store — graph traversal, vector search, Cypher queries, permanent persistence. Keeping them separate means the hot path never touches the disk-backed store.

**Why Hebbian scoring?**
Pure semantic similarity retrieves what is *related to the query*. Hebbian scoring retrieves what has been *useful before* in similar situations. The combination lets the service adapt over time — episodes that are repeatedly helpful together develop stronger associative links and surface earlier in future retrievals.

**Why a single `observe` endpoint?**
An agent should not need to decide where to store an observation or how to search for relevant context. The observe endpoint encapsulates the full memory lifecycle: storage routing, retrieval, summarization, and background consolidation — all triggered by one call.

**Why REM consolidation?**
Raw episodes are redundant, noisy, and expensive to search at scale. Periodic consolidation compresses them into structured knowledge, deduplicates overlapping observations, and produces compact summaries. This mirrors the function of sleep in biological memory: forgetting the noise, retaining the signal.

**Why DSPy?**
Structured extraction requires reliable, schema-validated LLM outputs. DSPy provides type-checked signatures with retry logic and adapter-based output parsing, making extraction robust across models and providers.
