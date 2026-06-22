# Causal-Aware Graph RAG Search — Design

**Date:** 2026-06-22
**Status:** Design (approved in brainstorming, pending spec review)
**Component:** `memory_service` retrieval / search

---

## Goal

Make Segnog search meaningfully more accurate by retrieving over the **graph structure** (entities, relationships, causal links) that the corpus already contains, instead of pure vector similarity. Keep it fast enough for agent memory recall, with a heavier path for human UI search.

## Problem (observed failure modes)

Current search (`search_knowledge` → `search_hybrid` → `search_by_vector`) is vector cosine similarity + label boost + temporal/Hebbian re-rank. Two failure modes were identified:

1. **Misses connected facts** — returns direct semantic matches but misses information reachable only through entity/relationship/causal links (e.g. asks about X, never surfaces that *X causes Y*). Multi-hop context is lost.
2. **Low precision** — vector similarity matches surface wording, not actual relevance; "similar but unconnected" results rank highly.

The graph already holds the structure to fix both, but search does not use it: `OntologyNode` entities, `RELATES` entity–entity edges, `Episode-[:ABOUT]->OntologyNode`, `Knowledge-[:DERIVED_FROM]->Episode`, and a full causal layer (`CausalClaim` + `CAUSE_ENTITY`/`EFFECT_ENTITY`/`CAUSES`).

## Approach

**Causal-aware, HippoRAG-style Personalized PageRank (PPR) retrieval**, tiered, bounded, default-on with a kill-switch. Chosen over Microsoft-style community-summary GraphRAG (overkill — targets global/synthesis questions we don't have) and rerank-only (fixes precision but not connected-facts).

Research basis:
- **HippoRAG** (NeurIPS 2024, arXiv:2405.14831) — PPR over an entity KG seeded by query concepts; +20% multi-hop QA, 6–13× faster / 10–30× cheaper than iterative retrieval. Core mechanism adopted.
- **LightRAG** (EMNLP 2025, arXiv:2410.05779) — dual-level (entity/theme) retrieval + incremental graph updates; validates the fast/accurate tiering and fits our constantly-changing graph.
- **Microsoft GraphRAG** (arXiv:2404.16130) — community summaries for global synthesis; parked as a future UI-synthesis option.

### Feasibility note (PPR on FalkorDB)
FalkorDB ships standard `algo.pageRank(label, rel)` but **not** Personalized (seeded) PageRank. The entity graph is small (~1,600 `OntologyNode`s), so PPR is computed **in Python (scipy sparse)** over a bounded seed-relevant subgraph per query — milliseconds, negligible CPU. No dependency on a FalkorDB feature that doesn't exist.

---

## Architecture

New retrieval pipeline behind the existing service methods (`search_knowledge`/`search_episodes`), so callers are unchanged. Gated by config: on → `GraphRetriever`; off → today's `search_hybrid` (unchanged).

```
Query
  ├─▶ [1] SEED     vector ANN seed (existing, index-backed) → top-N Knowledge + Episodes
  │                + anchor entities: query → OntologyNode(s) (name match + vector)
  ├─▶ [2] BUILD    assemble bounded PPR subgraph: anchor entities + their
  │                RELATES neighbours + causal neighbours (CAUSE/EFFECT_ENTITY),
  │                hop-limited (≤2)
  ├─▶ [3] PPR      Personalized PageRank (Python/scipy), seeded on anchor entities,
  │                propagating along RELATES + causal edges → relevance per entity
  ├─▶ [4] MAP      passage_score = blend(
  │                   Σ PPR(entities linked via ABOUT/DERIVED_FROM/CAUSE/EFFECT),
  │                   vector_similarity,         # for non-entity-bearing hits
  │                   evidence/confidence,       # causal claims
  │                   temporal + Hebbian)        # reuse scoring.py
  └─▶ [5] RANK     fast tier returns top_k; UI tier adds one MiniMax rerank/synthesis
```

### Components (each isolated + testable)

| Component | Responsibility | Depends on |
|---|---|---|
| `GraphRetriever` | orchestrates stages; owns tier flag + kill-switch | stores, PPR, reranker |
| `EntityAnchorResolver` | query → matching `OntologyNode` seeds | ontology store, embed |
| `PPRSubgraphBuilder` | bounded subgraph extraction (entities + RELATES + causal edges) | FalkorDB |
| `PersonalizedPageRank` | seeded PPR over the subgraph (scipy sparse) | numpy/scipy |
| `CandidateMapper` | entity PPR scores → passage/claim candidate scores | FalkorDB |
| `GraphReranker` | final blend (heuristic); LLM rerank for UI tier | scoring config, LLM client |

`search_by_vector` (now index-backed via PR #4523) is reused unchanged as the **stage-1 seed**.

---

## Causal integration

`CausalClaim`s bridge to the same `OntologyNode` entities PPR runs over, so causality is extra edges + extra retrievable nodes in the same graph — not a separate system.

1. **Causal edges in the PPR graph.** Each `CausalClaim` contributes a directed, typed, confidence-weighted edge `cause_entity →[causal,type,confidence]→ effect_entity`. PPR then propagates relevance along causal links (query about X surfaces what X causes/enables/prevents and downstream effects).
2. **`CausalClaim`s as first-class candidates.** They have embeddings + confidence + `SUPPORTS`/`CONTRADICTS` evidence. Scored by PPR mass of their cause/effect entities + claim-embedding vector similarity + evidence strength. Results include the causal *explanation*, not just isolated facts.
3. **Causal chains.** Bounded traversal along `CausalClaim-[:CAUSES]->CausalClaim` (and `CausalChain` `CHAIN_STEP`) retrieves a chain X→Y→Z when relevant.
4. **Type-awareness.** `causes/enables/prevents/inhibits` are preserved on retrieved claims (weight by confidence for PPR; keep type/sign on output) so "X prevents Y" is never conflated with "X causes Y".

### Graph schema referenced (from `causal_store.py`)
```
(:CausalClaim {cause_summary, effect_summary, causal_type, confidence, embedding})
(:Knowledge)-[:SUPPORTS|CONTRADICTS {weight}]->(:CausalClaim)
(:CausalClaim)-[:CAUSE_ENTITY]->(:OntologyNode)
(:CausalClaim)-[:EFFECT_ENTITY]->(:OntologyNode)
(:CausalClaim)-[:CAUSES]->(:CausalClaim)
(:CausalChain)-[:CHAIN_STEP {position}]->(:CausalClaim)
```

### Live data counts
_TBD — to be filled when `az containerapp exec` cooperates (the count query is a direct FalkorDB read). Prior log evidence confirms the layer is actively populated: "revised 1366 causal beliefs", "auto-chained 21 CAUSES edges", "stored N causal claims" per ontology pass. Entity graph ~1,600 OntologyNodes; ~9.1k Knowledge, ~3k Episode nodes with 768-dim embeddings._

---

## Tiers

- **Fast tier (agent memory recall):** stages 1–5 heuristic only, no LLM. Target sub-second. Used by observe/hydrate and high-volume recall.
- **Accurate tier (human UI search):** fast tier + one MiniMax call that reranks the top ~20 candidates (optionally returns a short cited synthesis). Target ≤ a few seconds.

Tier selected per request (caller passes a flag; default fast for service-internal, accurate for UI endpoints).

---

## Bounding & safety

The hard lesson from the go-dark incident is baked in:
- All traversals **hop-limited (≤2)** and **candidate-capped**.
- PPR runs over a **bounded seed-relevant subgraph**, not the whole graph.
- All FalkorDB reads inherit the deployed **5s query timeout** (`TIMEOUT_DEFAULT`).
- PPR is Python/scipy over a small sparse matrix (ms; no FalkorDB load).
- Entire pipeline behind **`MEMORY_SERVICE_SEARCH__GRAPH_RAG_ENABLED` (default true)** — set false to instantly revert to pure vector search.

---

## Configuration

```
[search]
graph_rag_enabled = true          # kill-switch; false = legacy vector search
ppr_max_hops = 2                  # subgraph expansion bound
ppr_damping = 0.85
ppr_seed_top_n = 10               # anchor entities seeded into PPR
candidate_cap = 200               # max candidates before rerank
# blend weights (sum ~1.0), all tunable
w_ppr = 0.45
w_vector = 0.30
w_causal_evidence = 0.10
w_temporal = 0.10
w_hebbian = 0.05
ui_llm_rerank = true              # accurate-tier LLM rerank/synthesis
```

---

## Testing & success metrics

- **Result-parity harness** (already built for the vector-index work) extended with a labelled set of multi-hop + causal queries.
- **Accuracy:** recall@k of known connected/causal facts vs the current vector baseline. Target: recover the "missed connected facts" (qualitative + labelled set).
- **Latency:** fast tier sub-second on agent recall; UI tier ≤ a few seconds. Benchmark before/after.
- **Stability:** re-run the go-dark + concurrent-search stress harnesses to prove bounded traversals never block FalkorDB (`/health` stays responsive, 0 restarts).
- **Kill-switch:** verify `graph_rag_enabled=false` produces byte-identical behaviour to current search.

## Dependencies / sequencing

1. Vector ANN index (PR #4523) — the stage-1 seed. Land first.
2. This pipeline builds on it. Knowledge path first; **Episode** path (reflection scan + `/episodes/search`) gets the same treatment as a follow-up.

## Out of scope (YAGNI)

- Microsoft-style community detection + LLM community summaries (global synthesis) — revisit only if "what are the themes" questions become a requirement.
- Replacing the embedding backend (separate latency lever; not a retrieval-accuracy change).
