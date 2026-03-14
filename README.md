# Segnog

> **Dal Segno** — *from the sign*. In music notation, *Dal Segno* instructs the performer to return to the segno mark (𝄋) and replay the passage — but with everything they have learned since the first time. The second pass through is never the same as the first.

Segnog is a memory microservice for AI agents. It stores what happened, distills what mattered, and returns the right context at the right moment — so the agent returns to the sign and plays it better.

---

## Philosophy

Most AI agents are amnesiac by default. They are stateless across conversations, unable to learn from prior experience, and forced to rediscover the same context on every new turn.

Segnog is built around three convictions:

**1. Memory has two layers.**
Short-term memory is fast, volatile, and session-scoped. Long-term memory is permanent, structured, and accumulates over time. These are different problems with different tools. Keeping them separate — DragonflyDB for hot sessions, FalkorDB for the persistent graph — means the hot path never pays the cost of the cold store.

**2. Relevance is not just semantic similarity.**
A keyword match tells you what is *related*. What you actually need is what was *useful before in similar situations*. Segnog scores every retrieval on three dimensions: how similar, how recent, and how often co-retrieved. Episodes that fire together, wire together.

**3. Consolidation should be unconscious.**
An agent should not have to decide how to manage its own memory. The observe endpoint handles everything in one call — store, retrieve, summarize, return context — while background workers consolidate experiences into knowledge asynchronously, the way biological memory is refined during sleep.

---

## The Observe Endpoint

Every interaction with memory happens through a single call to `/observe`:

```json
{
  "session_id": "agent-session-42",
  "content": "The user asked about last quarter's deployment incident.",
  "timestamp": "2025-11-01T14:30:00Z",
  "source": "chat"
}
```

Segnog returns a context passage the agent can use immediately:

```json
{
  "episode_uuid": "550e8400-e29b-41d4-a716-446655440000",
  "context": "In Q3, the v2.3 deployment on October 14th caused a memory leak in the worker pool. It was patched in v2.3.1 the following morning after Caroline identified the root cause in the session logs..."
}
```

The agent does not choose where to store, what to search, or how to format. Observe handles all of it.

---

## Memory Architecture

```
                            Agent (caller)
                                  │
                    ┌─────────────┴──────────────┐
                    │                            │
              gRPC :50051                  REST :9000
                    │                            │
                    └──────────┬─────────────────┘
                               │
                    MemoryServiceHandler
                               │
              ┌────────────────┼────────────────┐
              │                │                │
        DragonflyDB         FalkorDB           NATS
        Short-Term          Long-Term        Event Bus
        (:6381)             (:6380)          (:4222)
              │                │
         Sessions           Episodes
         Hot cache          Knowledge
         TTL 24h            Artifacts
                            Entities
                            Ontology
                            Hebbian Graph
                               │
                    ┌──────────┴──────────┐
                    │                     │
             CurationWorker         REMSweepWorker
             (NATS, threshold-       (periodic sweep,
              triggered)             decay, fallback)
```

All six services — DragonflyDB, FalkorDB, NATS, gRPC server, REST server, and background workers — run inside a single Docker container managed by supervisord.

---

## Two Memory Layers

### Short-Term Memory — DragonflyDB

DragonflyDB is the hot session cache. It holds the raw stream of observations for an active session, plus episodes and knowledge pre-fetched from FalkorDB on first contact.

Every session entry has:
- The raw content text
- Its embedding vector (for in-session semantic search)
- A timestamp and source label
- A 3D score: semantic + temporal + Hebbian

Sessions expire by TTL (default 24 hours). While a session is warm, all retrieval is in-memory — no FalkorDB query needed. Context generation costs one LLM call over cached data.

**Structure (per session key):**
```
session:{session_id}  →  list of entries
  [
    { content, embedding, score, source, timestamp },
    ...
  ]
```

The session can contain three types of entries:
1. **Local** — observations added in this session
2. **Hydrated episodes** — related episodes pulled from FalkorDB during cold start
3. **Hydrated knowledge** — knowledge entries pulled from FalkorDB on cold start
4. **Hydrated ontology** — entity profile summaries from OntologyNodes

### Long-Term Memory — FalkorDB

FalkorDB is the persistent property graph. It stores everything that survives a session: episodes as graph nodes with embeddings, structured knowledge extracted by LLM, named entities, and the ontology of known real-world entities.

**Node types:**

| Node | Purpose | Key properties |
|------|---------|----------------|
| `Episode` | A single observation | content, embedding, created\_at, consolidation\_status, activation\_count, knowledge\_extracted |
| `Knowledge` | A distilled fact or pattern | content, knowledge\_type (fact / pattern / insight / procedure), labels, confidence, embedding |
| `OntologyNode` | A real-world entity profile | name, schema\_type (Schema.org class), display\_name, summary (prose), embedding, source\_count |
| `Artifact` | Generated code, documents, tools | content, artifact\_type |
| `Label` | Semantic tag for knowledge | name |

**Edge types:**

| Edge | Meaning |
|------|---------|
| `FOLLOWS` | Sequential ordering within a group |
| `DUPLICATE_OF` | Episode deduplicated against an older one |
| `CO_ACTIVATED` | Hebbian co-occurrence: weight grows with co-retrieval |
| `DERIVED_FROM` | Knowledge node linked to its source episode |
| `REINFORCES` | Stronger link when near-duplicate knowledge would be created |
| `ABOUT` | Episode linked to the OntologyNode it concerns |
| `RELATES` | OntologyNode ↔ OntologyNode relationship (Schema.org predicate) |
| `HAS_LABEL` | Knowledge ↔ Label |

All FalkorDB queries filter by `group_id`. All session keys include `group_id`. Multiple agents or conversations can share the same instance without data leakage.

---

## The Observe Sequence

```
POST /observe
   │
   ├─ 1. Embed content  ──────────────────────────────── OpenAI embeddings API
   │
   ├─ 2. Store in DragonflyDB session
   │
   ├─ 3. Cold start? (session.count < 2)
   │       ├─ YES: Reinterpret query via DSPy (optimize for FalkorDB search)
   │       │       Search FalkorDB → pre-fill session cache with
   │       │         top episodes, knowledge, ontology nodes
   │       └─ NO:  Skip — session already warm
   │
   ├─ 4. Semantic search within DragonflyDB session  ─── in-memory cosine
   │       Apply 3D scoring to results
   │
   ├─ 5. LLM summarize session entries  ──────────────── DSPy ContextSummarization
   │
   ├─ 6. Return context to agent  ←─────────────── ~1–2 seconds total
   │
   └─ 7. Fire background tasks (non-blocking)
         ├─ Store episode to FalkorDB
         ├─ Extract knowledge from observation  (DSPy)
         │   └─ Set knowledge_extracted = true on Episode node
         ├─ Search FalkorDB + hydrate session cache
         ├─ Hebbian reinforcement on retrieved episodes
         └─ Judge observation type + importance
```

The agent receives its context in ~1–2 seconds. Everything that touches FalkorDB or calls LLMs for extraction happens asynchronously in the background.

---

## 3D Scoring

Every retrieval result is scored on three dimensions before ranking.

```
score = (1 − α − β) × semantic + α × freshness + β × hebbian

Defaults:
  α = 0.30  (temporal weight)
  β = 0.20  (Hebbian weight)
```

**Semantic** — cosine similarity between query embedding and result embedding.

**Temporal (freshness)** — hyperbolic decay from the moment of creation:
```
freshness = 1 / (1 + age_hours / half_life_hours)

Half-lives:
  Session entries:  0.5 hours
  Episodes:       168 hours  (1 week)
  Knowledge:      720 hours  (30 days)
```

**Hebbian (co-activation)** — reward for episodes that have been retrieved together repeatedly:
```
hebbian = 0.5 × activation_strength + 0.5 × co_activation_weight

activation_strength = log(1 + count) / log(1 + cap)

On each co-retrieval:
  new_weight = old_weight + lr × (1 − old_weight)   (lr = 0.1)
```

Co-activation weights grow asymptotically toward 1.0 and are never reset — only decayed slowly over time. Episodes that are repeatedly useful together develop stronger associative bonds and surface earlier in future retrievals.

---

## The Ontology Layer

The ontology is a persistent knowledge graph of real-world entities — people, organizations, places, and concepts — derived from conversations and structured according to [Schema.org](https://schema.org).

### OntologyNode

Each OntologyNode represents one real-world entity:

```
OntologyNode {
  name:         "Caroline Zhao"
  schema_type:  "Person"           ← Schema.org class
  display_name: "Caroline"
  summary:      "Caroline is a software engineer at Meridian Labs...
                 She deployed v2.3 in October and identified the
                 memory leak in the worker pool."
  embedding:    [0.12, -0.34, ...]  ← vecf32, searchable by cosine
  source_count: 7                  ← how many episodes informed this
  group_id:     "locomo-conv-0"
}
```

The summary is a prose passage that accumulates meaning over time. Every time a new episode mentions Caroline, the LLM updates the summary to incorporate new information. The embedding is re-computed on each update, so ontology search reflects the current state of the entity.

### Schema.org as the Type System

All entity types and relationship predicates come from the Schema.org vocabulary (930 classes, 1520 properties), parsed from the JSON-LD specification at startup. This gives a shared, standardized type system across all extractions.

Ontological inference runs at write time:
- **Symmetric predicates** (knows, spouse, sibling, colleague) — when A knows B, B knows A is automatically stored
- **Inverse pairs** (worksFor ↔ employedBy, memberOf ↔ member) — inverse edges stored automatically

### How the Ontology Is Updated

After each consolidation batch, `update_group_ontology()` runs:

```
8a. Extract entities  ──────────── DSPy EntityExtractionSignature
     Each entity → (name, Schema.org class)
     Filtered: no image entities, no names > 4 words

8b. Upsert OntologyNodes
     MERGE by (name, group_id)
     └─ If new: create node + embed summary
     └─ If existing: LLM updates summary with new episode context
                     re-embed updated summary
                     increment source_count

8c. Extract relationships  ──────── DSPy RelationshipExtractionSignature
     Each triple: (subject, predicate, object)
     Validated against Schema.org domain/range rules
     Stored as RELATES edges with confidence score
     Inverse + symmetric edges inferred automatically

8d. Link episodes → OntologyNodes
     ABOUT edges from episode to all entities it mentions
```

### Ontology in Retrieval

During a cold start or background hydration, OntologyNode summaries are pulled into the session cache alongside episodes and knowledge. They appear as a different source type (`ontology_node`) and are included in the summarization context — so the agent's context passage can reference what Segnog knows about the entities involved.

---

## Background Consolidation (REM)

Inspired by biological REM sleep — the phase in which the brain consolidates short-term experiences into long-term structured memory — the REM worker runs periodic cycles over pending episodes.

```
Every 60 seconds:
  │
  ├─ 1. Find groups with ≥3 pending raw episodes
  │       Prioritize by: volume × age
  │
  ├─ 2. Deduplication check
  │       Compare each pending episode against consolidated ones
  │       ≥0.90 cosine → mark DUPLICATE_OF, skip
  │       < 0.90         → include in curation batch
  │
  ├─ 3. Curation (DSPy)
  │       Extract knowledge → store with dedup (REINFORCES if near-dup)
  │       Mark episodes consolidated
  │
  ├─ 4. Temporal compression
  │       Compress unique episodes into a single reflection episode
  │       Link reflection → sources via DERIVED_FROM
  │
  ├─ 5. Ontology update (Steps 8a–8d above)
  │
  └─ 6. Hebbian decay
          Decay all CO_ACTIVATED edge weights by 0.01 / 168h
          Prune edges below 0.01
```

### Event-Driven Mode (NATS)

When NATS is enabled, consolidation does not wait for the 60-second polling interval. The CurationWorker subscribes to `memory.episode.stored.*` events, accumulates episodes per group, and triggers curation as soon as a group reaches the threshold (default 3 episodes) or has been waiting longer than 30 seconds. Lower latency; the polling REMSweepWorker still runs as a fallback for orphaned groups.

---

## Knowledge Extraction

At two points in the pipeline — inside `background_hydrate` (per-observation) and inside the REM curation batch — Segnog extracts structured knowledge from episode content using DSPy.

Each knowledge entry is:
```
Knowledge {
  content:        "Caroline identified the memory leak in the worker pool"
  knowledge_type: "fact"
  labels:         ["deployment", "infrastructure", "incident"]
  confidence:     0.91
  event_date:     "2025-10-15"
}
```

**Deduplication:** before storing, Segnog checks for existing knowledge with cosine similarity ≥ 0.90. If found, it creates a `REINFORCES` edge instead of a duplicate node — reinforcing the existing entry and preserving provenance.

The `knowledge_extracted` flag on each Episode node ensures that if the per-observation extraction succeeded, the CurationWorker skips re-extraction for that episode when it processes the batch — preventing duplicates while still running ontology update, consolidation, and compression.

---

## Benchmark — LoCoMo

LoCoMo (Long Conversation Modeling) is a QA benchmark over long multi-session dialogues. Questions span five categories: direct recall, temporal reasoning, cross-session inference, open-domain, and adversarial.

Segnog is evaluated by ingesting a full conversation and then answering questions using the retrieved context. F1 measures token overlap between the predicted and ground-truth answer. LLM Judge is a binary CORRECT/WRONG verdict from a separate evaluator model.

### Results

Ingestion method: `/observe` per session (knowledge extracted per-episode in `background_hydrate`).
Retrieval mode: `episodes_knowledge` (episodes + knowledge hybrid, top-25 + top-10).

| Category | n | F1 | LLM Judge |
|----------|---|-----|-----------|
| 1. Single-hop | 32 | 0.777 | 0.758 |
| 2. Temporal | 37 | 0.946 | 0.912 |
| 3. Multi-hop | 13 | 0.673 | 0.673 |
| 4. Open-domain | 70 | 0.873 | 0.871 |
| 5. Adversarial | 47 | 0.872 | — |
| **Overall (cat. 1–4)** | **152** | **0.853** | **0.840** |

Temporal reasoning scores highest — the combination of timestamped episodes and temporal decay in the 3D scorer naturally handles date-relative questions. Multi-hop reasoning (cross-session inference) is the hardest category: it requires linking facts across separate sessions, which the Hebbian graph helps but does not fully solve.

### Running the Benchmark

```bash
# Ingest conversation 0
python -m benchmarks.locomo run --phase ingest --conversations 0

# Evaluate
export OPENROUTER_API_KEY=sk-or-v1-...
python -m benchmarks.locomo run \
  --phase evaluate --conversations 0 --trials 3 \
  --retrieval episodes_knowledge --use-llm-judge
```

---

## Deployment

All six services (DragonflyDB, FalkorDB, NATS, gRPC, REST, workers) run in a single container managed by supervisord.

```bash
# Build and start
docker-compose build
docker-compose up -d

# Health check
curl http://localhost:9000/health
```

**API keys** (environment or `.secrets.toml`):
```bash
MEMORY_SERVICE_EMBEDDINGS__API_KEY=sk-or-v1-...
MEMORY_SERVICE_LLM__API_KEY=sk-or-v1-...
```

Named Docker volumes persist data across rebuilds:
- `dragonfly_data` — session cache + event streams
- `falkordb_data` — episodes, knowledge, ontology
- `nats_data` — event stream persistence

---

## Configuration Reference

```toml
[default.scoring]
episode_half_life_hours = 168.0     # 1 week
episode_alpha           = 0.3       # temporal weight
knowledge_half_life_hours = 720.0   # 30 days
knowledge_alpha         = 0.2

[default.hebbian]
learning_rate      = 0.1
beta_episode       = 0.2            # Hebbian weight in 3D score
decay_rate         = 0.01
decay_interval_hours = 168
activation_cap     = 1000

[default.background]
interval_seconds           = 60
batch_size                 = 5
min_episodes_for_processing = 3

[default.session]
ttl_seconds = 86400                 # 24 hours

[default.nats]
enabled                     = false
url                         = "nats://localhost:4222"
curation_min_episodes       = 3
curation_max_wait_seconds   = 30.0
curation_max_concurrent     = 2
```

---

## File Structure

```
agent-memory-service/
│
├── Dockerfile                      # All-in-one container (supervisord)
├── docker-compose.yml
├── settings.toml                   # Service configuration
│
├── src/memory_service/
│   ├── main.py                     # Entry point, startup sequence
│   │
│   ├── core/
│   │   ├── observe.py              # observe_core() — hot path + background_hydrate
│   │   └── hebbian.py              # Co-activation reinforcement
│   │
│   ├── storage/
│   │   ├── dragonfly.py            # DragonflyDB client (sessions, events)
│   │   ├── episode_store.py        # FalkorDB episodes
│   │   ├── knowledge_store.py      # FalkorDB knowledge
│   │   ├── artifact_store.py       # FalkorDB artifacts
│   │   └── ontology_store.py       # FalkorDB OntologyNodes
│   │
│   ├── scoring.py                  # 3D scoring functions
│   │
│   ├── smart/                      # DSPy-powered LLM operations
│   │   ├── summarize_context.py
│   │   ├── extract_knowledge.py
│   │   ├── extract_entities.py
│   │   ├── extract_relationships.py
│   │   ├── ontology_pipeline.py    # update_group_ontology() — Steps 8a–8d
│   │   ├── reinterpret.py
│   │   └── judge_observation.py
│   │
│   ├── events/
│   │   ├── curation_worker.py      # NATS event-driven curation
│   │   └── rem_sweep_worker.py     # NATS periodic sweep
│   │
│   ├── background/
│   │   └── rem_worker.py           # Polling-based REM consolidation
│   │
│   ├── rest/                       # FastAPI REST server
│   └── grpc/                       # gRPC server
│
└── benchmarks/locomo/              # LoCoMo benchmark suite
    ├── runner.py
    ├── ingest.py
    ├── retrieve.py
    ├── answer.py
    └── score.py
```
