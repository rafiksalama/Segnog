"""
Phase 1 Integration Tests — OntologyStore

Tests OntologyStore against a live FalkorDB instance.

Prerequisites:
  - FalkorDB running on localhost:6380
  - Embedding API accessible (uses settings.toml config)

Run:
    python -m pytest tests/integration/test_ontology_store.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from memory_service.config import get_embedding_api_key, get_embedding_base_url, get_embedding_model
from memory_service.schema_org import SchemaOrgOntology
from memory_service.storage.ontology_store import OntologyStore

JSONLD_PATH = Path(__file__).parents[2] / "data" / "schemaorg-current-https.jsonld"
TEST_GROUP = "test-ontology-integration"

# Shared SchemaOrgOntology — created once, pure Python, no event loop needed
_ONTO = SchemaOrgOntology(JSONLD_PATH)


# ---------------------------------------------------------------------------
# Fixtures — function-scoped to avoid event loop cross-contamination
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def store() -> OntologyStore:
    """Create a fresh OntologyStore for each test."""
    from openai import AsyncOpenAI
    from falkordb.asyncio import FalkorDB

    db = FalkorDB(host="localhost", port=6380)
    graph = db.select_graph("episode_store")

    client = AsyncOpenAI(
        api_key=get_embedding_api_key(),
        base_url=get_embedding_base_url(),
    )
    s = OntologyStore(
        graph=graph,
        openai_client=client,
        embedding_model=get_embedding_model(),
        ontology=_ONTO,
    )
    await s.ensure_indexes()

    # Clean slate before each test
    await graph.query(
        "MATCH (n:OntologyNode {group_id: $gid}) DETACH DELETE n",
        params={"gid": TEST_GROUP},
    )

    yield s

    # Cleanup after each test
    await graph.query(
        "MATCH (n:OntologyNode {group_id: $gid}) DETACH DELETE n",
        params={"gid": TEST_GROUP},
    )


# ---------------------------------------------------------------------------
# T1.1 — upsert creates node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_creates(store):
    uuid = await store.upsert_node(
        name="Caroline",
        schema_type="Person",
        display_name="Caroline",
        summary="Caroline is a Swedish woman living in Stockholm.",
        group_id=TEST_GROUP,
    )
    assert uuid, "Expected non-empty uuid"

    node = await store.get_node("caroline", TEST_GROUP)
    assert node is not None
    assert node["schema_type"] == "Person"
    assert "Stockholm" in node["summary"]
    assert node["source_count"] == 1


# ---------------------------------------------------------------------------
# T1.2 — upsert merges (no duplicate)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_merges_no_duplicate(store):
    await store.upsert_node("Caroline", "Person", "Caroline", "Summary v1.", TEST_GROUP)
    await store.upsert_node(
        "Caroline", "Person", "Caroline", "Summary v2 with more info.", TEST_GROUP
    )

    result = await store._graph.ro_query(
        "MATCH (n:OntologyNode {name: 'caroline', group_id: $gid}) RETURN count(n) AS cnt",
        params={"gid": TEST_GROUP},
    )
    count = result.result_set[0][0]
    assert count == 1, f"Expected 1 node, got {count}"

    node = await store.get_node("caroline", TEST_GROUP)
    assert node["source_count"] == 2
    assert "v2" in node["summary"]


# ---------------------------------------------------------------------------
# T1.3 — schema_type normalized via full Schema.org
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_normalizes_schema_type(store):
    await store.upsert_node("Acme Corp", "company", "Acme Corp", "A corporation.", TEST_GROUP)
    node = await store.get_node("acme-corp", TEST_GROUP)
    assert node is not None
    assert node["schema_type"] == "Organization", f"Got: {node['schema_type']}"


# ---------------------------------------------------------------------------
# T1.4 — symmetric inference: knows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_symmetric_knows(store):
    await store.upsert_node("Caroline", "Person", "Caroline", "...", TEST_GROUP)
    await store.upsert_node("Melanie", "Person", "Melanie", "...", TEST_GROUP)
    await store.store_relates("caroline", "knows", "melanie", TEST_GROUP)

    fwd = await store._graph.ro_query(
        "MATCH (a:OntologyNode {name:'caroline', group_id:$gid})"
        "-[r:RELATES {predicate:'knows', group_id:$gid}]->"
        "(b:OntologyNode {name:'melanie', group_id:$gid}) RETURN r.predicate",
        params={"gid": TEST_GROUP},
    )
    assert len(fwd.result_set) == 1, "Missing forward knows edge"

    rev = await store._graph.ro_query(
        "MATCH (a:OntologyNode {name:'melanie', group_id:$gid})"
        "-[r:RELATES {predicate:'knows', group_id:$gid}]->"
        "(b:OntologyNode {name:'caroline', group_id:$gid}) RETURN r.predicate",
        params={"gid": TEST_GROUP},
    )
    assert len(rev.result_set) == 1, "Missing symmetric reverse knows edge"


# ---------------------------------------------------------------------------
# T1.5 — inverse inference: parent ↔ children
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inverse_parent_children(store):
    await store.upsert_node("Caroline", "Person", "Caroline", "...", TEST_GROUP)
    await store.upsert_node("Julia Horrocks", "Person", "Julia Horrocks", "...", TEST_GROUP)
    await store.store_relates("caroline", "parent", "julia-horrocks", TEST_GROUP)

    fwd = await store._graph.ro_query(
        "MATCH (a:OntologyNode {name:'caroline', group_id:$gid})"
        "-[r:RELATES {predicate:'parent', group_id:$gid}]->"
        "(b:OntologyNode {name:'julia-horrocks', group_id:$gid}) RETURN r.predicate",
        params={"gid": TEST_GROUP},
    )
    assert len(fwd.result_set) == 1, "Missing forward parent edge"

    inv = await store._graph.ro_query(
        "MATCH (a:OntologyNode {name:'julia-horrocks', group_id:$gid})"
        "-[r:RELATES {predicate:'children', group_id:$gid}]->"
        "(b:OntologyNode {name:'caroline', group_id:$gid}) RETURN r.predicate",
        params={"gid": TEST_GROUP},
    )
    assert len(inv.result_set) == 1, "Missing inverse children edge"


# ---------------------------------------------------------------------------
# T1.6 — memberOf → member (declared inverseOf in Schema.org JSON-LD)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inverse_member_of(store):
    await store.upsert_node("Caroline", "Person", "Caroline", "...", TEST_GROUP)
    await store.upsert_node("Spotify", "Organization", "Spotify", "...", TEST_GROUP)
    await store.store_relates("caroline", "memberOf", "spotify", TEST_GROUP)

    inv = await store._graph.ro_query(
        "MATCH (a:OntologyNode {name:'spotify', group_id:$gid})"
        "-[r:RELATES {predicate:'member', group_id:$gid}]->"
        "(b:OntologyNode {name:'caroline', group_id:$gid}) RETURN r.predicate",
        params={"gid": TEST_GROUP},
    )
    assert len(inv.result_set) == 1, "Missing inverse member edge for memberOf"


# ---------------------------------------------------------------------------
# T1.7 — predicate normalization in store_relates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_relates_normalizes_predicate(store):
    await store.upsert_node("Caroline", "Person", "Caroline", "...", TEST_GROUP)
    await store.upsert_node("Stockholm", "Place", "Stockholm", "...", TEST_GROUP)
    await store.store_relates("caroline", "lives-in", "stockholm", TEST_GROUP)

    result = await store._graph.ro_query(
        "MATCH (a:OntologyNode {name:'caroline', group_id:$gid})"
        "-[r:RELATES {predicate:'homeLocation', group_id:$gid}]->"
        "(b:OntologyNode {name:'stockholm', group_id:$gid}) RETURN r.predicate",
        params={"gid": TEST_GROUP},
    )
    assert len(result.result_set) == 1, (
        "Legacy predicate 'lives-in' not normalized to 'homeLocation'"
    )


# ---------------------------------------------------------------------------
# T1.8 — embedding search returns correct entity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_nodes(store):
    await store.upsert_node(
        "Caroline",
        "Person",
        "Caroline",
        "Caroline works at Spotify in Stockholm, Sweden as a music curator.",
        TEST_GROUP,
    )
    await store.upsert_node(
        "Spotify",
        "Organization",
        "Spotify",
        "Spotify is a music streaming service headquartered in Stockholm.",
        TEST_GROUP,
    )

    embedding = await store._embed("where does Caroline work?")
    results = await store.search_nodes(embedding, top_k=2, group_id=TEST_GROUP, min_score=0.0)

    assert len(results) > 0, "No results returned"
    names = [r["name"] for r in results]
    assert "caroline" in names, f"Expected 'caroline' in {names}"
    for r in results:
        assert 0.0 <= r["score"] <= 1.0


# ---------------------------------------------------------------------------
# T1.9 — ABOUT edge: episode → ontology node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_about(store):
    await store.upsert_node("Caroline", "Person", "Caroline", "...", TEST_GROUP)

    ep_uuid = "test-ep-uuid-123"
    await store._graph.query(
        "MERGE (e:Episode {uuid: $uuid}) SET e.group_id = $gid, e.content = 'test'",
        params={"uuid": ep_uuid, "gid": TEST_GROUP},
    )

    await store.link_about(ep_uuid, "caroline", TEST_GROUP)

    result = await store._graph.ro_query(
        "MATCH (:Episode {uuid:$ep_uuid})-[:ABOUT]->(n:OntologyNode {name:'caroline', group_id:$gid})"
        " RETURN n.name",
        params={"ep_uuid": ep_uuid, "gid": TEST_GROUP},
    )
    assert len(result.result_set) == 1, "Missing ABOUT edge"

    await store._graph.query(
        "MATCH (e:Episode {uuid:$uuid}) DETACH DELETE e", params={"uuid": ep_uuid}
    )


# ---------------------------------------------------------------------------
# T1.10 — list_nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_nodes(store):
    await store.upsert_node("Caroline", "Person", "Caroline", "...", TEST_GROUP)
    await store.upsert_node("Spotify", "Organization", "Spotify", "...", TEST_GROUP)
    await store.upsert_node("Stockholm", "Place", "Stockholm", "...", TEST_GROUP)

    all_nodes = await store.list_nodes(group_id=TEST_GROUP)
    assert len(all_nodes) == 3

    persons = await store.list_nodes(group_id=TEST_GROUP, schema_type="Person")
    assert len(persons) == 1
    assert persons[0]["name"] == "caroline"
