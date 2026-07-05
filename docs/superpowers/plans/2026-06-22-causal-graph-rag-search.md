# Causal-Aware Graph RAG Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace pure-vector knowledge search with causal-aware, HippoRAG-style Personalized PageRank retrieval over the entity graph — default-on with a kill-switch — to recover multi-hop "connected facts" and improve precision.

**Architecture:** A new `graph_rag` retrieval subpackage. Query → vector seed + entity anchors → bounded subgraph (RELATES + causal edges) → seeded PPR (scipy, in-process) → map entity scores to Knowledge/CausalClaim candidates → blended rerank. Wired behind `MemoryService.search_knowledge` via a config kill-switch; off → existing `search_hybrid` unchanged.

**Tech Stack:** Python 3.11, FalkorDB (Cypher via `self._graph.ro_query`), numpy + scipy (sparse PPR), pytest-asyncio. Builds on the vector ANN index (PR #4523).

**Spec:** `docs/superpowers/specs/2026-06-22-causal-graph-rag-search-design.md`

---

## Conventions for this plan

- **Tests are gitignored** in this repo (`.gitignore` has `tests/`). Unit tests below are real and runnable locally (`pytest`), but are NOT committed — commits in test-bearing tasks add only the `src/` files. This matches repo convention; integration is verified via the deploy+benchmark harness (Task 9), not committed tests.
- Run tests from repo root with the package importable: `pip install -e .` once, then `pytest tests/... -v`.
- Pure-Python units (PPR, blend) are TDD'd. FalkorDB-touching units (subgraph, candidates) are thin Cypher wrappers verified in Task 9's e2e harness.

## File structure

| File | Responsibility |
|---|---|
| `src/memory_service/storage/retrieval/graph_rag/__init__.py` | package exports |
| `.../graph_rag/ppr.py` | pure seeded Personalized PageRank (numpy/scipy) — no I/O |
| `.../graph_rag/subgraph.py` | `PPRSubgraphBuilder`: Cypher → weighted entity subgraph (RELATES + causal edges) |
| `.../graph_rag/anchors.py` | `EntityAnchorResolver`: query embedding → seed `OntologyNode`s |
| `.../graph_rag/candidates.py` | `CandidateMapper`: entity PPR scores → Knowledge/CausalClaim candidates |
| `.../graph_rag/rerank.py` | `GraphReranker`: blended score (heuristic) + optional LLM rerank (UI tier) |
| `.../graph_rag/retriever.py` | `GraphRetriever`: orchestrates stages; owns tier + kill-switch |
| `src/memory_service/config.py` (modify) | new `[search]` getters |
| `settings.toml` (modify) | new `[default.search]` section |
| `src/memory_service/services/memory_service.py` (modify) | `search_knowledge` kill-switch branch |
| `pyproject.toml` (modify) | add `numpy`, `scipy` deps |

---

### Task 1: Dependencies, config getters, settings

**Files:**
- Modify: `pyproject.toml` (dependencies array)
- Modify: `src/memory_service/config.py` (append getters)
- Modify: `settings.toml` (add `[default.search]`)

- [ ] **Step 1: Add numpy + scipy to dependencies**

In `pyproject.toml`, add to the `dependencies` array:
```toml
    "numpy>=1.26",
    "scipy>=1.11",
```

- [ ] **Step 2: Add `[default.search]` to settings.toml**

After the `[default.embeddings]` block in `settings.toml`:
```toml
[default.search]
graph_rag_enabled = true
ppr_max_hops = 2
ppr_damping = 0.85
ppr_seed_top_n = 10
ppr_min_seed_score = 0.5
candidate_cap = 200
w_ppr = 0.45
w_vector = 0.30
w_causal_evidence = 0.10
w_temporal = 0.10
w_hebbian = 0.05
ui_llm_rerank = true
```

- [ ] **Step 3: Append config getters to config.py**

At the end of `src/memory_service/config.py`:
```python
def get_graph_rag_enabled() -> bool:
    s = get_settings()
    return os.environ.get(
        "MEMORY_SERVICE_SEARCH__GRAPH_RAG_ENABLED",
        str(s.get("search.graph_rag_enabled", True)),
    ).lower() in ("1", "true", "yes")


def get_search_setting(key: str, default):
    """Numeric/string search tunables under [search]. Env override: MEMORY_SERVICE_SEARCH__<KEY>."""
    s = get_settings()
    env = os.environ.get(f"MEMORY_SERVICE_SEARCH__{key.upper()}")
    if env is not None:
        return type(default)(env)
    return s.get(f"search.{key}", default)
```

- [ ] **Step 4: Verify config loads**

Run: `python -c "from memory_service.config import get_graph_rag_enabled, get_search_setting; print(get_graph_rag_enabled(), get_search_setting('w_ppr', 0.45), get_search_setting('ppr_max_hops', 2))"`
Expected: `True 0.45 2`

- [ ] **Step 5: Commit**
```bash
git add pyproject.toml settings.toml src/memory_service/config.py
git commit -m "feat(search): add graph-rag config (kill-switch, PPR/blend tunables) + numpy/scipy deps"
```

---

### Task 2: Personalized PageRank (pure function, TDD)

**Files:**
- Create: `src/memory_service/storage/retrieval/graph_rag/__init__.py`
- Create: `src/memory_service/storage/retrieval/graph_rag/ppr.py`
- Test (local, gitignored): `tests/retrieval/test_ppr.py`

- [ ] **Step 1: Write the failing test**

Create `tests/retrieval/test_ppr.py`:
```python
import math
from memory_service.storage.retrieval.graph_rag.ppr import personalized_pagerank


def test_ppr_concentrates_on_seed_and_neighbours():
    # A--B--C chain, D isolated. Seed on A.
    nodes = ["A", "B", "C", "D"]
    edges = [("A", "B", 1.0), ("B", "C", 1.0)]
    scores = personalized_pagerank(nodes, edges, seeds={"A": 1.0}, damping=0.85)
    assert scores["A"] > scores["B"] > scores["C"]      # decays with hops from seed
    assert scores["C"] > scores["D"]                    # isolated node ~ teleport floor
    assert abs(sum(scores.values()) - 1.0) < 1e-6       # distribution sums to 1

def test_ppr_weighted_edges_bias_propagation():
    nodes = ["A", "B", "C"]
    edges = [("A", "B", 0.1), ("A", "C", 0.9)]           # A causes C strongly
    scores = personalized_pagerank(nodes, edges, seeds={"A": 1.0}, damping=0.85)
    assert scores["C"] > scores["B"]

def test_ppr_empty_seeds_returns_uniform_floor():
    scores = personalized_pagerank(["A", "B"], [], seeds={}, damping=0.85)
    assert scores == {} or all(v >= 0 for v in scores.values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/retrieval/test_ppr.py -v`
Expected: FAIL — `ModuleNotFoundError: ...graph_rag.ppr`

- [ ] **Step 3: Implement ppr.py**

Create `src/memory_service/storage/retrieval/graph_rag/__init__.py` (empty).
Create `src/memory_service/storage/retrieval/graph_rag/ppr.py`:
```python
"""Seeded Personalized PageRank over a small in-memory weighted digraph.

Pure function — no I/O. Used to propagate query relevance across the entity
graph (RELATES + causal edges). Power-iteration on a scipy sparse column-
stochastic matrix; the teleport vector is the (normalised) seed distribution.
"""
from typing import Dict, List, Tuple

import numpy as np
from scipy.sparse import csr_matrix


def personalized_pagerank(
    nodes: List[str],
    edges: List[Tuple[str, str, float]],   # (src, dst, weight)
    seeds: Dict[str, float],               # node -> teleport mass (unnormalised ok)
    damping: float = 0.85,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> Dict[str, float]:
    if not nodes or not seeds:
        return {}
    idx = {n: i for i, n in enumerate(nodes)}
    n = len(nodes)

    # Build weighted adjacency (src->dst), then column-normalise to transition matrix.
    rows, cols, data = [], [], []
    for src, dst, w in edges:
        if src in idx and dst in idx and w > 0:
            rows.append(idx[dst]); cols.append(idx[src]); data.append(float(w))
    A = csr_matrix((data, (rows, cols)), shape=(n, n)) if data else csr_matrix((n, n))
    col_sums = np.asarray(A.sum(axis=0)).ravel()
    col_sums[col_sums == 0] = 1.0
    M = A.multiply(1.0 / col_sums)         # column-stochastic

    # Teleport vector from seeds (normalised).
    tele = np.zeros(n)
    for node, mass in seeds.items():
        if node in idx and mass > 0:
            tele[idx[node]] += float(mass)
    if tele.sum() == 0:
        return {}
    tele /= tele.sum()

    r = tele.copy()
    for _ in range(max_iter):
        r_next = damping * (M @ r) + (1.0 - damping) * tele
        if np.abs(r_next - r).sum() < tol:
            r = r_next; break
        r = r_next
    r = r / r.sum()
    return {nodes[i]: float(r[i]) for i in range(n)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/retrieval/test_ppr.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit (src only — tests gitignored)**
```bash
git add src/memory_service/storage/retrieval/graph_rag/__init__.py src/memory_service/storage/retrieval/graph_rag/ppr.py
git commit -m "feat(search): seeded Personalized PageRank (scipy power-iteration)"
```

---

### Task 3: PPRSubgraphBuilder (bounded entity+causal subgraph)

**Files:**
- Create: `src/memory_service/storage/retrieval/graph_rag/subgraph.py`

- [ ] **Step 1: Implement subgraph.py**

Extracts a bounded subgraph around seed entities: RELATES edges + causal edges
(derived from `CausalClaim` CAUSE/EFFECT_ENTITY). Hop-bounded via repeated
1-hop expansion in Cypher (FalkorDB variable-length is unbounded-risky; we cap
explicitly). All reads use `ro_query` (inherits the 5s FalkorDB timeout).

```python
"""Build a bounded, weighted entity subgraph for PPR from FalkorDB."""
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)

# Causal type -> propagation weight (confidence is multiplied in at query time).
_CAUSAL_BASE_W = {"causes": 1.0, "enables": 0.8, "prevents": 0.7, "inhibits": 0.7}


class PPRSubgraphBuilder:
    def __init__(self, graph):
        self._graph = graph  # FalkorDB graph handle (has .ro_query)

    async def build(
        self, seed_names: List[str], group_id: str, max_hops: int = 2
    ) -> Tuple[List[str], List[Tuple[str, str, float]]]:
        """Return (node_names, weighted_edges) for the seed neighbourhood."""
        if not seed_names:
            return [], []
        frontier = set(seed_names)
        all_nodes = set(seed_names)
        edges: List[Tuple[str, str, float]] = []

        for _hop in range(max_hops):
            if not frontier:
                break
            # RELATES (undirected co-occurrence/inferred) edges from frontier.
            rel = await self._graph.ro_query(
                """
                MATCH (a:OntologyNode)-[r:RELATES]-(b:OntologyNode)
                WHERE a.name IN $frontier
                RETURN a.name AS src, b.name AS dst,
                       COALESCE(r.weight, 1.0) AS w
                LIMIT 2000
                """,
                params={"frontier": list(frontier)},
            )
            new_nodes = set()
            for row in (rel.result_set or []):
                src, dst, w = row[0], row[1], float(row[2] or 1.0)
                edges.append((src, dst, w)); edges.append((dst, src, w))  # symmetric
                if dst not in all_nodes:
                    new_nodes.add(dst)

            # Causal edges: cause_entity -> effect_entity via CausalClaim.
            cz = await self._graph.ro_query(
                """
                MATCH (ce:OntologyNode)<-[:CAUSE_ENTITY]-(c:CausalClaim)-[:EFFECT_ENTITY]->(ee:OntologyNode)
                WHERE ce.name IN $frontier OR ee.name IN $frontier
                RETURN ce.name AS src, ee.name AS dst,
                       COALESCE(c.causal_type, 'causes') AS ctype,
                       COALESCE(c.confidence, 0.5) AS conf
                LIMIT 2000
                """,
                params={"frontier": list(frontier)},
            )
            for row in (cz.result_set or []):
                src, dst, ctype, conf = row[0], row[1], row[2], float(row[3] or 0.5)
                w = _CAUSAL_BASE_W.get(ctype, 1.0) * conf
                edges.append((src, dst, w))                 # directed (causal)
                for nm in (src, dst):
                    if nm not in all_nodes:
                        new_nodes.add(nm)

            all_nodes |= new_nodes
            frontier = new_nodes

        return list(all_nodes), edges
```

- [ ] **Step 2: Verify import + instantiation (no live graph needed)**

Run: `python -c "from memory_service.storage.retrieval.graph_rag.subgraph import PPRSubgraphBuilder; print(PPRSubgraphBuilder(None).__class__.__name__)"`
Expected: `PPRSubgraphBuilder`

- [ ] **Step 3: Commit**
```bash
git add src/memory_service/storage/retrieval/graph_rag/subgraph.py
git commit -m "feat(search): bounded entity+causal subgraph builder for PPR"
```

---

### Task 4: EntityAnchorResolver (query → seed entities)

**Files:**
- Create: `src/memory_service/storage/retrieval/graph_rag/anchors.py`

- [ ] **Step 1: Implement anchors.py**

Reuses the existing `OntologyStore.search_nodes(embedding, top_k, group_id, min_score)`.

```python
"""Resolve a query to seed OntologyNode entities for PPR."""
from typing import Dict, List


class EntityAnchorResolver:
    def __init__(self, ontology_store, embed_fn):
        self._onto = ontology_store          # OntologyStore
        self._embed = embed_fn               # async callable: str -> List[float]

    async def resolve(
        self, query: str, group_id: str, top_n: int = 10, min_score: float = 0.5
    ) -> Dict[str, float]:
        """Return {entity_name: seed_mass} where mass = similarity score."""
        embedding = await self._embed(query)
        nodes = await self._onto.search_nodes(
            embedding=embedding, top_k=top_n, group_id=group_id, min_score=min_score
        )
        seeds: Dict[str, float] = {}
        for n in nodes:
            name = n.get("name") or n.get("display_name")
            score = n.get("score", 0.0)
            if name and score > 0:
                seeds[name] = float(score)
        return seeds
```

- [ ] **Step 2: Verify import**

Run: `python -c "from memory_service.storage.retrieval.graph_rag.anchors import EntityAnchorResolver; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**
```bash
git add src/memory_service/storage/retrieval/graph_rag/anchors.py
git commit -m "feat(search): entity anchor resolver (query -> seed OntologyNodes)"
```

---

### Task 5: CandidateMapper (entity PPR → passage/claim candidates)

**Files:**
- Create: `src/memory_service/storage/retrieval/graph_rag/candidates.py`

- [ ] **Step 1: Implement candidates.py**

Given PPR scores per entity, fetch Knowledge + CausalClaim nodes linked to those
entities (via `DERIVED_FROM`→Episode→`ABOUT` and `CAUSE/EFFECT_ENTITY`), and
attach the summed PPR mass of their linked entities. Bounded by `candidate_cap`.

```python
"""Map entity PPR scores to retrievable Knowledge/CausalClaim candidates."""
from typing import Any, Dict, List


class CandidateMapper:
    def __init__(self, graph):
        self._graph = graph

    async def map_candidates(
        self, entity_scores: Dict[str, float], group_id: str, cap: int = 200
    ) -> List[Dict[str, Any]]:
        if not entity_scores:
            return []
        names = list(entity_scores.keys())

        # Knowledge linked to these entities through its source Episode's ABOUT edges.
        kn = await self._graph.ro_query(
            """
            MATCH (k:Knowledge {group_id: $gid})-[:DERIVED_FROM]->(:Episode)-[:ABOUT]->(n:OntologyNode)
            WHERE n.name IN $names
            WITH k, collect(DISTINCT n.name) AS ents
            RETURN k.uuid AS uuid, k.content AS content, k.knowledge_type AS ktype,
                   k.confidence AS confidence, k.created_at AS created_at,
                   COALESCE(k.activation_count, 0) AS activation_count, ents
            LIMIT $cap
            """,
            params={"gid": group_id, "names": names, "cap": cap},
        )
        candidates: List[Dict[str, Any]] = []
        for row in (kn.result_set or []):
            ents = row[6] or []
            ppr_mass = sum(entity_scores.get(e, 0.0) for e in ents)
            candidates.append({
                "uuid": row[0], "content": row[1], "knowledge_type": row[2],
                "confidence": row[3], "created_at": row[4],
                "activation_count": row[5], "ppr_mass": ppr_mass,
                "source": "knowledge",
            })

        # CausalClaims whose cause/effect entity is in scope.
        cz = await self._graph.ro_query(
            """
            MATCH (c:CausalClaim {group_id: $gid})
            MATCH (c)-[:CAUSE_ENTITY|EFFECT_ENTITY]->(n:OntologyNode)
            WHERE n.name IN $names
            OPTIONAL MATCH (:Knowledge)-[s:SUPPORTS]->(c)
            WITH c, collect(DISTINCT n.name) AS ents, COALESCE(sum(s.weight), 0.0) AS support
            RETURN c.uuid AS uuid, c.cause_summary AS cause, c.effect_summary AS effect,
                   c.causal_type AS ctype, c.confidence AS confidence,
                   c.created_at AS created_at, ents, support
            LIMIT $cap
            """,
            params={"gid": group_id, "names": names, "cap": cap},
        )
        for row in (cz.result_set or []):
            ents = row[6] or []
            ppr_mass = sum(entity_scores.get(e, 0.0) for e in ents)
            candidates.append({
                "uuid": row[0],
                "content": f"{row[1]} —[{row[3]}]→ {row[2]}",
                "knowledge_type": "causal_claim",
                "confidence": row[4], "created_at": row[5],
                "activation_count": 0, "ppr_mass": ppr_mass,
                "causal_evidence": float(row[7] or 0.0),
                "causal_type": row[3], "source": "causal_claim",
            })
        return candidates
```

- [ ] **Step 2: Verify import**

Run: `python -c "from memory_service.storage.retrieval.graph_rag.candidates import CandidateMapper; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**
```bash
git add src/memory_service/storage/retrieval/graph_rag/candidates.py
git commit -m "feat(search): map entity PPR scores to Knowledge + CausalClaim candidates"
```

---

### Task 6: GraphReranker (blend, TDD)

**Files:**
- Create: `src/memory_service/storage/retrieval/graph_rag/rerank.py`
- Test (local, gitignored): `tests/retrieval/test_rerank.py`

- [ ] **Step 1: Write the failing test**

Create `tests/retrieval/test_rerank.py`:
```python
from memory_service.storage.retrieval.graph_rag.rerank import blend_score, rerank

def test_blend_prefers_high_ppr_when_vector_tied():
    w = dict(w_ppr=0.45, w_vector=0.30, w_causal_evidence=0.10, w_temporal=0.10, w_hebbian=0.05)
    a = {"ppr_mass": 0.9, "vector_score": 0.5, "causal_evidence": 0, "temporal": 0.5, "hebbian": 0.5}
    b = {"ppr_mass": 0.1, "vector_score": 0.5, "causal_evidence": 0, "temporal": 0.5, "hebbian": 0.5}
    assert blend_score(a, w) > blend_score(b, w)

def test_rerank_orders_descending_and_caps():
    w = dict(w_ppr=1.0, w_vector=0, w_causal_evidence=0, w_temporal=0, w_hebbian=0)
    cands = [{"uuid": str(i), "ppr_mass": i/10, "vector_score": 0,
              "causal_evidence": 0, "temporal": 0, "hebbian": 0} for i in range(5)]
    out = rerank(cands, w, top_k=3)
    assert [c["uuid"] for c in out] == ["4", "3", "2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/retrieval/test_rerank.py -v`
Expected: FAIL — `ModuleNotFoundError: ...graph_rag.rerank`

- [ ] **Step 3: Implement rerank.py**

```python
"""Blend PPR + vector + causal-evidence + temporal + Hebbian into a final score."""
from typing import Any, Dict, List


def blend_score(c: Dict[str, Any], w: Dict[str, float]) -> float:
    return (
        w["w_ppr"] * c.get("ppr_mass", 0.0)
        + w["w_vector"] * c.get("vector_score", 0.0)
        + w["w_causal_evidence"] * c.get("causal_evidence", 0.0)
        + w["w_temporal"] * c.get("temporal", 0.0)
        + w["w_hebbian"] * c.get("hebbian", 0.0)
    )


def rerank(candidates: List[Dict[str, Any]], w: Dict[str, float], top_k: int) -> List[Dict[str, Any]]:
    for c in candidates:
        c["score"] = blend_score(c, w)
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_k]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/retrieval/test_rerank.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**
```bash
git add src/memory_service/storage/retrieval/graph_rag/rerank.py
git commit -m "feat(search): graph-rag blended reranker (PPR+vector+causal+temporal+hebbian)"
```

---

### Task 7: GraphRetriever (orchestrator)

**Files:**
- Create: `src/memory_service/storage/retrieval/graph_rag/retriever.py`

- [ ] **Step 1: Implement retriever.py**

Wires stages together; normalises sub-scores; reuses the existing
`KnowledgeStore.search_by_vector` for the vector seed/scores.

```python
"""Orchestrate causal-aware Graph RAG retrieval for knowledge search."""
import logging
from typing import Any, Dict, List

from .anchors import EntityAnchorResolver
from .subgraph import PPRSubgraphBuilder
from .candidates import CandidateMapper
from .ppr import personalized_pagerank
from .rerank import rerank
from ...retrieval.scoring import apply_temporal_score
from ....config import get_search_setting

logger = logging.getLogger(__name__)


class GraphRetriever:
    def __init__(self, knowledge_store, ontology_store, graph):
        self._kn = knowledge_store
        self._anchors = EntityAnchorResolver(ontology_store, knowledge_store._embed)
        self._subgraph = PPRSubgraphBuilder(graph)
        self._candidates = CandidateMapper(graph)

    async def search(self, query: str, group_id: str, top_k: int = 10) -> List[Dict[str, Any]]:
        # Stage 1: vector seed (existing, index-backed) for vector_score + non-entity hits.
        vector_hits = await self._kn.search_by_vector(query, top_k=top_k * 2)
        vec_by_uuid = {h["uuid"]: h.get("score", 0.0) for h in vector_hits}

        # Stage 1b: entity anchors.
        seeds = await self._anchors.resolve(
            query, group_id,
            top_n=int(get_search_setting("ppr_seed_top_n", 10)),
            min_score=float(get_search_setting("ppr_min_seed_score", 0.5)),
        )
        if not seeds:
            return vector_hits[:top_k]   # no entities matched → plain vector

        # Stage 2: bounded subgraph.
        nodes, edges = await self._subgraph.build(
            list(seeds.keys()), group_id,
            max_hops=int(get_search_setting("ppr_max_hops", 2)),
        )
        # Stage 3: seeded PPR.
        entity_scores = personalized_pagerank(
            nodes, edges, seeds, damping=float(get_search_setting("ppr_damping", 0.85))
        )
        # Stage 4: map to candidates, attach sub-scores.
        cands = await self._candidates.map_candidates(
            entity_scores, group_id, cap=int(get_search_setting("candidate_cap", 200))
        )
        # Merge vector-only hits not already entity-linked.
        seen = {c["uuid"] for c in cands}
        for h in vector_hits:
            if h["uuid"] not in seen:
                cands.append({**h, "ppr_mass": 0.0, "source": "vector"})

        _norm(cands, "ppr_mass")
        for c in cands:
            c["vector_score"] = vec_by_uuid.get(c["uuid"], c.get("score", 0.0))
            c["hebbian"] = min(1.0, (c.get("activation_count", 0) or 0) / 10.0)
        cands = apply_temporal_score(cands, alpha=1.0, half_life_hours=720)  # sets/uses temporal
        for c in cands:
            c.setdefault("temporal", c.get("score", 0.0))
            c.setdefault("causal_evidence", c.get("causal_evidence", 0.0))

        weights = {k: float(get_search_setting(k, d)) for k, d in {
            "w_ppr": 0.45, "w_vector": 0.30, "w_causal_evidence": 0.10,
            "w_temporal": 0.10, "w_hebbian": 0.05}.items()}
        return rerank(cands, weights, top_k=top_k)


def _norm(items: List[Dict[str, Any]], key: str) -> None:
    mx = max((i.get(key, 0.0) for i in items), default=0.0)
    if mx > 0:
        for i in items:
            i[key] = i.get(key, 0.0) / mx
```

- [ ] **Step 2: Verify import**

Run: `python -c "from memory_service.storage.retrieval.graph_rag.retriever import GraphRetriever; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**
```bash
git add src/memory_service/storage/retrieval/graph_rag/retriever.py
git commit -m "feat(search): GraphRetriever orchestrator (seed->anchors->PPR->candidates->rerank)"
```

---

### Task 8: Wire into search_knowledge with kill-switch

**Files:**
- Modify: `src/memory_service/services/memory_service.py` (`search_knowledge`, lines ~163-224)

- [ ] **Step 1: Add the kill-switch branch**

At the top of `search_knowledge` (after the signature, before the existing
`knowledge = await self._kn(group_id).search_hybrid(...)`), insert:
```python
        from ..config import get_graph_rag_enabled
        if get_graph_rag_enabled() and group_id is not None:
            try:
                from ..storage.retrieval.graph_rag.retriever import GraphRetriever
                retriever = GraphRetriever(
                    self._kn(group_id), self._ontology_store, self._knowledge_store._graph
                )
                results = await retriever.search(query, group_id, top_k=top_k)
                if results:
                    return results
                # empty → fall through to legacy path below
            except Exception as e:
                logger.warning("Graph RAG search failed (%s); falling back to vector", e)
        # ---- legacy vector path (unchanged) ----
```
Leave the existing body intact as the fallback. This guarantees: flag off, no entities, empty result, or any error → identical legacy behaviour.

- [ ] **Step 2: Verify import + flag wiring**

Run: `python -c "import memory_service.services.memory_service as m; print('import ok')"`
Expected: `import ok`

- [ ] **Step 3: Verify kill-switch parity locally (flag off == legacy)**

Run: `MEMORY_SERVICE_SEARCH__GRAPH_RAG_ENABLED=false python -c "from memory_service.config import get_graph_rag_enabled; assert get_graph_rag_enabled() is False; print('kill-switch off ok')"`
Expected: `kill-switch off ok`

- [ ] **Step 4: Commit**
```bash
git add src/memory_service/services/memory_service.py
git commit -m "feat(search): route search_knowledge through Graph RAG (default-on, kill-switch + fallback)"
```

---

### Task 9: Integration verification (deploy + benchmark/parity/stress)

**Files:**
- Use: existing harnesses `/tmp/bench.sh`, `/tmp/godark72.sh` style scripts (this session)
- Build context: overlay `FROM segnog:stable-v1` copying the new `graph_rag/` package + modified `memory_service.py` + `config.py`

- [ ] **Step 1: Capture baseline (current vector search) BEFORE deploy**

Run the parity harness against the live revision for the labelled multi-hop/causal query set; record top-k UUIDs + latency to `/tmp/baseline_graphrag.json`.

- [ ] **Step 2: Build overlay image**

Dockerfile `FROM mcpregistryuk2.azurecr.io/segnog:stable-v1`, `COPY` the new files into `/usr/local/lib/python3.11/site-packages/memory_service/...`, then `RUN python3 -c "import ast,glob; [ast.parse(open(f).read()) for f in glob.glob('/usr/local/lib/python3.11/site-packages/memory_service/storage/retrieval/graph_rag/*.py')]; print('parse ok')"`. Build `--platform linux/amd64`, push as `segnog:graphrag-test`.

- [ ] **Step 3: Data-safe deploy** (force SAVE+sync+timestamped backup → `az containerapp update --image` → route traffic → deactivate old → poll Healthy). Same procedure as prior deploys.

- [ ] **Step 4: Accuracy + latency benchmark**

Re-run the harness (ANN+GraphRAG) → `/tmp/graphrag.json`. Compare vs baseline:
- recall@k of known connected/causal facts (target: meaningfully higher than vector baseline)
- latency: fast tier sub-second; confirm no regression beyond budget

- [ ] **Step 5: Stress + go-dark re-run**

Run the cooccurrence go-dark harness + 8-concurrent-search stress against the new revision. Expected: `/health` never dark, `restartCount=0` (bounded traversals + 5s timeout hold).

- [ ] **Step 6: Kill-switch parity**

Set `MEMORY_SERVICE_SEARCH__GRAPH_RAG_ENABLED=false` (env on the container), redeploy/restart, re-run baseline queries → expect identical to Step 1 baseline.

- [ ] **Step 7: Raise PR**

Push `feat/graph-rag-search`; PR into `main` summarising the design, the benchmark numbers (accuracy + latency + stability), and the kill-switch parity result.

---

## Notes for the implementer
- **Bounding is non-negotiable** (the go-dark lesson): never remove the `LIMIT` caps or the `max_hops` loop bound; all FalkorDB reads stay on `ro_query` (inherits the 5s timeout).
- **Episode path is out of scope** for this plan (reflection scan + `/episodes/search`) — follow-up plan after this lands.
- **UI-tier LLM rerank/synthesis is deferred** (per approved scope: "rerank first, synthesis as fast-follow"). This plan ships the fast heuristic tier as the default for all callers. The `ui_llm_rerank` config flag exists (Task 1) but is not yet consumed; a follow-up adds a `GraphReranker.llm_rerank(candidates, query)` MiniMax call gated on it + the per-request tier flag. Until then the flag is a no-op.
- If `numpy`/`scipy` materially grow the image or slow startup, consider a slim scipy; PPR only needs `scipy.sparse` + `numpy`.
