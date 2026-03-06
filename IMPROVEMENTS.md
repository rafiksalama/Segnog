# Segnog — Consolidated Improvement Roadmap

Synthesized from three sources:
1. **10-Gap Analysis** — neuroscience-inspired gaps in agent memory systems
2. **Hippocampus Architecture** — competing system achieving 91.1% on LoCoMo (cumulative mode)
3. **Benchmark Weak Spots** — our LoCoMo results (F1 = 0.643 overall)

Current baseline (LoCoMo, grok-4.1-fast, qwen3-embedding-8b):

| Category | F1 | Weakness Level |
|----------|-----|----------------|
| Single-hop | 0.564 | Medium |
| Temporal | 0.691 | Low |
| Multi-hop | 0.366 | **Critical** |
| Open-domain | 0.683 | Low |
| Adversarial | 0.962 | None |
| **Overall (1-4)** | **0.643** | |

---

## Tier 1: High Impact (directly improves benchmark scores)

### 1. LLM-as-Judge Scoring
**Source**: Hippocampus comparison, LoCoMo standard practice
**Status**: Not implemented
**Effort**: Small

Our F1 metric (token overlap) and their accuracy metric (LLM-as-judge) aren't comparable. We need LLM-as-judge to benchmark on equal footing. Most published LoCoMo results use it.

**Implementation**: Add `--use-llm-judge` to benchmark, have grok judge whether the prediction answers the question correctly (binary yes/no). Report both F1 and accuracy.

### 2. Multi-Hop Graph Expansion
**Source**: Hippocampus (multi-hop traversal), Gap 9 (context-dependent retrieval), benchmark weakness
**Status**: Single-hop FOLLOWS expansion exists but is rarely used
**Effort**: Medium

Our worst category (F1 = 0.366). Hippocampus scores 87.5% here by expanding through temporal, activation, and association edges. We currently only expand along FOLLOWS edges and only 1 hop.

**Implementation**:
- Expand along FOLLOWS + DERIVED_FROM edges during retrieval (2-3 hops)
- When a retrieved episode is a compressed/reflection node, automatically include its source raw episodes
- Add a `graph_expand` parameter to search that follows provenance chains
- Weight expanded results by hop distance (closer = higher score)

### 3. LLM-Guided Retrieval Ranking
**Source**: Hippocampus (PageIndex-inspired), existing `filter_memory_results` smart op
**Status**: Basic filter exists but is optional and rarely used in retrieval path
**Effort**: Medium

Pure vector similarity returns "similar" not "relevant." Hippocampus uses LLM to reason over cluster summaries and dynamically dig into relevant episodes.

**Implementation**:
- After vector retrieval returns top-k candidates, run an LLM reranking step
- Group retrieved episodes by temporal proximity, have LLM score relevance to query
- Integrate into the retrieval path (not just the startup pipeline)
- Add a `rerank` parameter to search endpoints

### 4. Entity Resolution
**Source**: Hippocampus (canonical IDs + alias resolution), Gap 8 (interference management)
**Status**: Not implemented
**Effort**: Medium-Large

Critical for cumulative mode where multiple conversations coexist. Without it, "Julia" in conversation 3 and "Julia" in conversation 7 are indistinguishable. Hippocampus maintains canonical entity IDs with alias resolution.

**Implementation**:
- Add an `Entity` node type to FalkorDB with canonical ID + aliases
- During episode storage, extract entities (LLM or NER) and link via `MENTIONS` edges
- Entity resolution: merge "Julia Horrocks", "julia@company.com", "J. Horrocks" → same node
- During retrieval, entity-aware search: query "Julia" retrieves all episodes mentioning that entity
- Prevents cross-contamination between conversations about different people with same name

---

## Tier 2: Medium Impact (architectural improvements)

### 5. Reconsolidation (Gap 2)
**Source**: 10-Gap Analysis
**Status**: Not implemented
**Effort**: Medium

When new information contradicts existing knowledge, the knowledge should be updated rather than just adding a new conflicting entry. Currently knowledge entries are immutable once created.

**Implementation**:
- During curation, check if new knowledge contradicts existing entries (vector similarity + LLM comparison)
- If contradiction found: update the existing knowledge entry with new content, bump confidence, add a `reconsolidated_at` timestamp
- Track reconsolidation history for audit trail
- Prevents knowledge graph bloat with contradictory entries

### 6. Active Forgetting (Gap 3)
**Source**: 10-Gap Analysis, Hippocampus (sleep consolidation prunes weak connections)
**Status**: Not implemented
**Effort**: Medium

The graph only grows, never shrinks. Low-value episodes and knowledge accumulate, degrading retrieval precision. Hippocampus prunes weak connections during sleep consolidation.

**Implementation**:
- Add a `relevance_score` or `access_count` to episodes and knowledge
- During REM cycles, identify candidates for forgetting:
  - Episodes never retrieved (low access count)
  - Knowledge with low confidence that was never validated
  - Old compressed episodes superseded by newer compressions
- "Forget" = mark as `archived` (soft delete) or reduce retrieval priority
- Keep a configurable retention policy (e.g., minimum age before eligible for forgetting)

### 7. Value-Aware Memory (Gap 4)
**Source**: 10-Gap Analysis (emotional/reward valence), Hippocampus (reward signals, Q-values, TD learning)
**Status**: Not implemented
**Effort**: Large

Currently all memories are treated as equally important. Hippocampus assigns reward signals from curiosity, conversational feedback, and decision outcomes, then uses these to bias retrieval.

**Implementation**:
- Add a `reward` field to episodes (default 0.0)
- Intrinsic reward: novelty score from embedding distance to existing prototypes
- Extrinsic reward: caller can pass feedback (`positive`/`negative`) linked to episodes
- Retrieval ranking: `final_score = vector_similarity * 0.7 + reward_signal * 0.3`
- Reward propagation: when a reflection is created, its reward flows back to source episodes

### 8. Schema-Based Abstraction / Prototype Engine (Gap 6)
**Source**: 10-Gap Analysis, Hippocampus (prototype engine with PDP, mitosis, merge)
**Status**: Not implemented
**Effort**: Large

Hippocampus builds learned concept representations (prototypes) that emerge from observation patterns. When value conflicts are detected, prototypes split (mitosis). Compatible prototypes merge.

**Implementation**:
- Add a `Prototype` node type — learned concept representations
- During REM consolidation, cluster similar knowledge entries → create/update prototypes
- Prototype activation during retrieval: query activates relevant prototypes, which boost related episodes
- Conflict detection: when a prototype has contradictory evidence, split into sub-prototypes
- This is the most ambitious change — consider a phased approach

---

## Tier 3: Lower Priority (valuable but less benchmark impact)

### 9. Source Monitoring (Gap 7)
**Source**: 10-Gap Analysis
**Status**: Partially implemented (DERIVED_FROM edges exist)
**Effort**: Small

Track confidence in source provenance. Currently DERIVED_FROM edges exist but carry no weight.

**Implementation**:
- Add `source_confidence` to DERIVED_FROM edges
- When knowledge is derived from multiple episodes, track agreement level
- Surface source information in retrieval results
- Flag low-confidence knowledge that needs verification

### 10. Prospective Memory (Gap 5)
**Source**: 10-Gap Analysis
**Status**: Not implemented
**Effort**: Medium

Remember to do things in the future — "remind me to follow up with Julia next week." No current system handles this.

**Implementation**:
- Add a `Reminder` node type with trigger conditions (time-based, event-based)
- Startup pipeline checks for active reminders matching current context
- Surface in briefing: "You planned to follow up on X"

### 11. Metamemory (Gap 10)
**Source**: 10-Gap Analysis
**Status**: Not implemented
**Effort**: Medium

The system should know what it knows and what it doesn't. Currently no mechanism for confidence calibration or "I don't know" responses.

**Implementation**:
- Track retrieval statistics: what queries return results vs. empty
- Confidence scoring: if retrieved episodes have low similarity scores, flag as uncertain
- "I don't know" detection: when no relevant memories exist, say so rather than hallucinating
- Memory coverage analysis: what topics are well-covered vs. sparse

### 12. Interference Management (Gap 8)
**Source**: 10-Gap Analysis
**Status**: Not implemented
**Effort**: Medium

Prevent retrieval interference where similar but irrelevant memories crowd out relevant ones. Related to entity resolution (#4).

**Implementation**:
- During retrieval, detect when results span multiple unrelated contexts
- Group results by entity/topic, present diverse results rather than all from one cluster
- Negative feedback loop: if a result was retrieved but not used, reduce its future ranking

### 13. Temporal Graph as First-Class Dimension
**Source**: Hippocampus (Raphtory), paper.md
**Status**: Timestamps as properties, not structural
**Effort**: Large (architecture change)

Hippocampus uses Raphtory where time is a structural dimension — you can window the graph to any point in time. FalkorDB stores timestamps as node properties, which limits temporal queries.

**Assessment**: This would require replacing FalkorDB with Raphtory or similar temporal graph DB. Too disruptive for now. The FOLLOWS edges + created_at properties give us 80% of the benefit. Revisit if temporal F1 drops.

### 14. Citation / Precedent Tracking
**Source**: Hippocampus (citation edges with authority tracking)
**Status**: Not implemented
**Effort**: Medium

Track which past decisions are cited as precedent by new decisions, building cumulative authority scores.

**Assessment**: Enterprise-relevant but doesn't impact LoCoMo scores. Park for now.

---

## Implementation Priority Order

Based on benchmark impact, effort, and architectural value:

| Priority | Improvement | Expected Impact | Effort |
|----------|-------------|-----------------|--------|
| **P0** | LLM-as-Judge Scoring (#1) | Enables comparison | Small |
| **P1** | Multi-Hop Graph Expansion (#2) | Multi-hop F1 ↑↑ | Medium |
| **P2** | LLM-Guided Retrieval Ranking (#3) | All categories ↑ | Medium |
| **P3** | Entity Resolution (#4) | Cumulative mode ↑↑ | Medium-Large |
| **P4** | Reconsolidation (#5) | Knowledge quality ↑ | Medium |
| **P5** | Active Forgetting (#6) | Retrieval precision ↑ | Medium |
| **P6** | Value-Aware Memory (#7) | Retrieval relevance ↑ | Large |
| **P7** | Schema/Prototypes (#8) | Concept learning | Large |
| Backlog | Source Monitoring, Prospective Memory, Metamemory, Interference, Temporal Graph, Citations | Various | Various |

---

## Completed

| Improvement | Status | Result |
|-------------|--------|--------|
| Gap 1: Offline Consolidation | **Done** | Episode lifecycle, priority-scored REM, temporal compression, source traceability |
| FOLLOWS edges | **Done** | Temporal chain between episodes |
| Temporal context | **Done** | date_time parsing in episode storage |
| F1 scoring normalization | **Done** | Proper token-level F1 |
| top_k increase | **Done** | 25 episodes, 10 knowledge |
