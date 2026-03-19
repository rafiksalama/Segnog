<p align="center">
  <img src="assets/segnog-logo.png" width="600" alt="Segnog" />
</p>

One endpoint. One Docker container. Your agent gets memory.

```bash
docker-compose up -d
```

```bash
curl -X POST http://localhost:9000/api/v1/memory/observe \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "agent-session-42",
    "content": "The user asked about last quarter's deployment incident.",
    "timestamp": "2025-11-01T14:30:00Z",
    "source": "chat"
  }'
```

```json
{
  "episode_uuid": "550e8400-e29b-41d4-a716-446655440000",
  "context": "In Q3, the v2.3 deployment on October 14th caused a memory leak in the worker pool. It was patched in v2.3.1 the following morning after Caroline identified the root cause in the session logs..."
}
```

That's it. The agent passes what it sees. Segnog returns what it should remember.

No schema to define. No retrieval logic to write. No storage layer to configure. Segnog decides what to store, what to search, and how to assemble the context. The agent just calls `/observe` at every turn and uses the returned `context` string.

---

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- An [OpenRouter](https://openrouter.ai) API key (used for embeddings and LLM extraction)

---

### Step 1 — Clone the repo

```bash
git clone https://github.com/rafiksalama/Segnog.git
cd Segnog
```

---

### Step 2 — Set your API key

Create `.secrets.toml` in the project root (it is gitignored):

```toml
# .secrets.toml
[default.embeddings]
api_key = "sk-or-v1-..."

[default.llm]
api_key = "sk-or-v1-..."
```

Both fields accept the same OpenRouter key. Alternatively, export environment variables:

```bash
export MEMORY_SERVICE_EMBEDDINGS__API_KEY=sk-or-v1-...
export MEMORY_SERVICE_LLM__API_KEY=sk-or-v1-...
```

---

### Step 3 — Build and start

```bash
docker-compose build
docker-compose up -d
```

The build step compiles the Python package and the React dashboard inside Docker. It takes a few minutes on first run.

To use a different host port:

```bash
PORT=8080 docker-compose up -d
```

---

### Step 4 — Verify

```bash
curl http://localhost:9000/health
# → {"status": "ok", "service": "agent-memory-service"}
```

---

### Step 5 — Open the dashboard

Visit **[http://localhost:9000](http://localhost:9000)** in a browser.

The dashboard shows live memory stats, sessions, episodes, the entity graph, and an Observe playground where you can send requests and inspect the returned context.

---

## How to Use Segnog

### From your agent — REST

Call `/observe` at every conversation turn. Pass what the agent just saw; use the returned `context` string as the memory prefix for the next LLM prompt.

```bash
curl -X POST http://localhost:9000/api/v1/memory/observe \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "my-agent-session",
    "content": "User: remind me what we decided about the API rate limits"
  }'
```

The response `context` field is a ready-to-use passage — inject it directly into your system prompt or as a `[MEMORY]` block before the user message.

---

### From your agent — Python client

```python
from memory_client import MemoryClient

# Connect (REST transport)
client = await MemoryClient.rest("http://localhost:9000", group_id="my-agent")

# Call observe at every turn
result = await client.observe("User asked about the deployment incident")
context = result["context"]   # inject into your next LLM call

await client.close()
```

Install the client:

```bash
pip install -e ./client
```

Or with gRPC transport (lower latency):

```python
client = await MemoryClient.grpc("localhost:50051", group_id="my-agent")
```

---

### From the dashboard

Open `http://localhost:9000` → **Observe** page. Type any message, click **Send**, and see the episode UUID and returned context live. Use this to inspect how Segnog retrieves and assembles memory before wiring it into your agent.

---

→ **[Full reference documentation](docs/REFERENCE.md)** — architecture, memory layers, observe sequence, 3D scoring, ontology, REM consolidation, configuration reference, benchmark results.

---

## How it stays simple

**One container holds everything.** DragonflyDB (session cache), FalkorDB (long-term graph), NATS (event bus), REST server, gRPC server, and background workers all run inside a single Docker container managed by supervisord. There is no external cluster to operate.

**One endpoint does everything.** `/observe` stores the current observation, searches for related memory, and returns a formatted context passage — all in a single call. Reading and writing are not separate operations.

**Data organises itself in the background.** The agent does not decide what is important or how to structure it. After returning the context, Segnog fires background tasks that extract knowledge, identify entities, consolidate episodes, and maintain a graph of who knows what. This happens asynchronously — the agent's response is not delayed.

**Memory has two layers, kept separate.** DragonflyDB is the hot session cache — fast, in-memory, TTL-scoped. FalkorDB is the persistent graph — structured, searchable across sessions. The hot path never touches the graph. The graph is populated in the background, then pulled into the session on the next cold start.

---

## Architecture

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

All six services run inside a single Docker container managed by supervisord.

---

## Name

> **Dal Segno** — *from the sign*. In music notation, *Dal Segno* instructs the performer to return to the segno mark (𝄋) and replay the passage — but with everything they have learned since the first time. The second pass through is never the same as the first.

---

## Philosophy

Most AI agents are amnesiac by default. They are stateless across conversations, unable to learn from prior experience, and forced to rediscover the same context on every new turn.

Segnog is built around three convictions:

**1. Memory has two layers.**
Short-term memory is fast, volatile, and session-scoped. Long-term memory is permanent, structured, and accumulates over time. These are different problems with different tools. Keeping them separate — DragonflyDB for hot sessions, FalkorDB for the persistent graph — means the hot path never pays the cost of the cold store.

**2. Relevance is not just semantic similarity.**
A keyword match tells you what is *related*. What you actually need is what was *useful before in similar situations*. When reading from the session cache, Segnog re-scores results on three dimensions: how similar, how recent, and how often co-retrieved. Episodes that fire together, wire together.

**3. Consolidation should be unconscious.**
An agent should not have to decide how to manage its own memory. The observe endpoint handles everything in one call — store, retrieve, summarize, return context — while background workers consolidate experiences into knowledge asynchronously, the way biological memory is refined during sleep.
