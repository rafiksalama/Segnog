<p align="center">
  <img src="assets/segnog-logo.png" width="600" alt="Segnog" />
</p>

Agentic memory, we are all getting obsessed with them, for the right reasons. LLMs cannot remember a thing, you need to constantly tell them every time what we were doing, and what we want to do, and here is everything else you need to know. A common problem for everything I try to build is a good memory,  and I wanted a very simple one API call memory, and it handles everything internally, one docker container, so a weekend project Segnog, that I kept iterating on it in the evenings, suspiciously good, for now. 

The trick it uses, is very simple, short memory fast, using Redis cache and embeddings for indexing. Long memory using Knowledge Graph and embeddings on the content and the Ontology terms. Internally it has a NATS event bus to sort out all artifacts internally. Like a good boy I used Schema.org for the Ontology, and dspy for optimizing prompts based on the context. Thanks Claude for all the help 🙃 

## Name

> **Dal Segno** — *from the sign*. In music notation, *Dal Segno* instructs the performer to return to the segno mark (𝄋) and replay the passage — but with everything they have learned since the first time. The second pass through is never the same as the first.

## How it stays simple

**One container holds everything.** DragonflyDB (session cache), FalkorDB (long-term graph), NATS (event bus), REST server, gRPC server, and background workers all run inside a single Docker container managed by supervisord. There is no external cluster to operate.

**One endpoint does everything.** `/observe` stores the current observation, searches for related memory, and returns a formatted context passage — all in a single call. Reading and writing are not separate operations.

**Data organises itself in the background.** The agent does not decide what is important or how to structure it. After returning the context, Segnog fires background tasks that extract knowledge, identify entities, consolidate episodes, and maintain a graph of who knows what. This happens asynchronously — the agent's response is not delayed.

**Memory has two layers, kept separate.** DragonflyDB is the hot session cache — fast, in-memory, TTL-scoped. FalkorDB is the persistent graph — structured, searchable across sessions. The hot path never touches the graph. The graph is populated in the background, then pulled into the session on the next cold start.

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
  "context": "In Q3, the v2.3 deployment on October 14th caused a memory leak in the worker pool. It was patched in v2.3.1 the following morning after Caroline identified the root cause in the session logs...",
  "session_id": "agent-session-42",
  "parent_session_id": null
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

<p align="center">
  <img src="assets/Dashboard.png" width="600" alt="Dashboard" />
</p>

The dashboard has seven pages:

| Page | What it shows |
|---|---|
| **Dashboard** | Service health grid, observe/search latency (p50 · p95), hydrate stats, and REM pipeline status — all live. |
| **Reporting** | Aggregate counters (episodes, knowledge nodes, ontology entities, active sessions), full per-endpoint latency chart with p50/p95/p99/max, and a scrollable event history log. |
| **Sessions** | A collapsible tree of all sessions. Parent-child relationships are visualised as indented branches — click ▶/▼ to expand or collapse. Selecting a session shows its latest episodes in the right panel, with a breadcrumb trail showing the full ancestor path (e.g. `project-x › task-1 › subtask-1a`). |
| **Memory Graph** | An interactive canvas graph of all ontology entities (nodes) and their relationships (edges). Switch between Hub, Force, Radial, Hierarchical and other layout modes. Click a node to see its Schema.org type and prose summary. |
| **Observe** | A live playground. Type any message, set a session ID, and click Send to call `/observe` directly and inspect the returned context. |
| **REM Monitor** | Status of the background consolidation pipeline: pending episodes, Hebbian edge count, ontology entity count, sweep cycle latency. |
| **Configuration** | All current configuration values from `settings.toml` — scoring weights, Hebbian parameters, background worker intervals, NATS settings. |

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

### Session identity

The simplest way to start a new session is to call `/pipelines/startup` without a `group_id`. Segnog generates a UUID, registers the session, and returns it so you can use it for every subsequent `/observe` call.

```bash
# Start a session — get back a UUID
SESSION=$(curl -s -X POST http://localhost:9000/api/v1/memory/pipelines/startup \
  -H "Content-Type: application/json" \
  -d '{"task": "Fix the authentication bug in the login flow"}' \
  | jq -r '.session_id')

# Use that UUID for every observe call in this session
curl -X POST http://localhost:9000/api/v1/memory/observe \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SESSION\", \"content\": \"Found the bug in auth/token.py line 42\"}"
```

If you already have a meaningful identifier (e.g. a workflow ID from your orchestrator), pass it as `group_id` and it will be echoed back as `session_id`.

---

### Hierarchical sessions

Sessions can be nested — a child session automatically inherits memory from all its ancestors at query time. The agent in `subtask-1a` sees everything from `task-1` and `project-x` without any extra logic.

```bash
# Root session
curl -X POST http://localhost:9000/api/v1/memory/observe \
  -H "Content-Type: application/json" \
  -d '{"session_id": "project-x", "content": "Building a search engine"}'

# Child session — links to project-x
curl -X POST http://localhost:9000/api/v1/memory/observe \
  -H "Content-Type: application/json" \
  -d '{"session_id": "task-1", "parent_session_id": "project-x", "content": "Working on indexing pipeline"}'

# Grandchild session — links to task-1
curl -X POST http://localhost:9000/api/v1/memory/observe \
  -H "Content-Type: application/json" \
  -d '{"session_id": "subtask-1a", "parent_session_id": "task-1", "content": "Implementing tokenizer"}'

# Query from the grandchild — context includes episodes from ALL ancestors
curl -X POST http://localhost:9000/api/v1/memory/observe \
  -H "Content-Type: application/json" \
  -d '{"session_id": "subtask-1a", "content": "What are we building?", "read_only": true}'
```

Session links are created lazily on first write — no pre-registration needed. The hierarchy is visible in the dashboard Sessions page as a collapsible tree.

---

### Global knowledge search

`/knowledge/search` can search across **all sessions** by omitting `group_id`. Useful for cross-session discovery or building a retrieval layer on top of the full knowledge base.

```bash
# Scoped to one session
curl -X POST http://localhost:9000/api/v1/memory/knowledge/search \
  -H "Content-Type: application/json" \
  -d '{"group_id": "my-agent-42", "query": "rate limit policy", "top_k": 5}'

# Global — searches all knowledge nodes regardless of session
curl -X POST http://localhost:9000/api/v1/memory/knowledge/search \
  -H "Content-Type: application/json" \
  -d '{"query": "rate limit policy", "top_k": 5}'
```

---

---

## API Specification

Segnog publishes a machine-readable OpenAPI 3.x spec and interactive docs at the API prefix, so any service or agent can discover its capabilities programmatically:

| URL | What it serves |
|---|---|
| `GET /api/v1/memory` | Discovery manifest — service name, version, and links to all endpoint groups |
| `GET /api/v1/memory/openapi.json` | Full OpenAPI 3.x spec (JSON) |
| `GET /api/v1/memory/docs` | Swagger UI — interactive browser exploration |
| `GET /api/v1/memory/redoc` | ReDoc — alternative rendered documentation |

```bash
# Fetch the spec programmatically
curl http://localhost:9000/api/v1/memory/openapi.json | python3 -m json.tool | head -30
```

---

→ **[Full reference documentation](docs/REFERENCE.md)** — architecture, memory layers, observe sequence, 3D scoring, ontology, REM consolidation, configuration reference, benchmark results.

→ **[REST API reference](docs/API.md)** — every endpoint with request/response shapes and examples.



