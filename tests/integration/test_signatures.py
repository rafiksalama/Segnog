"""
Phase 2 Integration Tests — DSPy Signatures

Tests extract_relationships() and update_ontology_summary() against the live LLM API.

Prerequisites:
  - LLM API key configured (settings.toml or environment)

Run:
    python -m pytest tests/integration/test_signatures.py -v
"""

import pytest

from memory_service.smart.extract_relationships import extract_relationships
from memory_service.smart.update_ontology import update_ontology_summary

# LoCoMo-inspired conversation excerpt
LOCOMO_EXCERPT = """Session 1 — 7:55 pm on 9 June, 2023
Caroline: My mum Julia Horrocks is a nurse at the NHS in London.
Melanie: That's cool! How long has she been there?
Caroline: About 10 years. I grew up in Stockholm though, now living here.
Melanie: I know, you're so Swedish! I work at Spotify by the way.
Caroline: Oh amazing! I love Spotify. My best friend Emma got married last week in Gothenburg.
Melanie: How lovely! Did you go?
Caroline: Yes! It was a beautiful ceremony.
"""

# Valid Schema.org class names — extracted types must be a subset of these
_VALID_SCHEMA_TYPES = {
    "Person", "Organization", "Place", "Event", "Product", "Action", "Thing",
    # Common subclasses the LLM might pick
    "LocalBusiness", "Hospital", "City", "Country", "Corporation",
    "CollegeOrUniversity", "School", "MusicGroup", "NGO",
}


# ---------------------------------------------------------------------------
# T2.1 — T2.3: Relationship extraction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_relationship_extraction_returns_list():
    """T2.1 — Returns a non-empty list of dicts with required keys."""
    rels = await extract_relationships(LOCOMO_EXCERPT)
    assert isinstance(rels, list), "Expected list"
    assert len(rels) > 0, "Expected at least one relationship"

    required_keys = {"subject", "subject_norm", "subject_type", "predicate",
                     "object", "object_norm", "object_type", "confidence"}
    for r in rels:
        missing = required_keys - set(r.keys())
        assert not missing, f"Missing keys {missing} in relationship: {r}"


@pytest.mark.asyncio
async def test_relationship_extraction_schema_org_predicates():
    """T2.2 — All predicates are Schema.org camelCase (no legacy hyphens)."""
    from pathlib import Path
    from memory_service.schema_org import SchemaOrgOntology

    jsonld_path = Path(__file__).parents[2] / "data" / "schemaorg-current-https.jsonld"
    onto = SchemaOrgOntology(jsonld_path)

    rels = await extract_relationships(LOCOMO_EXCERPT)
    assert len(rels) > 0

    for r in rels:
        pred = r["predicate"]
        # No legacy hyphens after normalization
        assert "-" not in pred, f"Legacy hyphen in predicate: {pred!r}"
        # Must be a valid Schema.org property (normalization guarantees this)
        assert pred in onto._properties or pred == "relatedTo", (
            f"Predicate not in Schema.org: {pred!r}"
        )


@pytest.mark.asyncio
async def test_relationship_extraction_schema_org_types():
    """T2.3 — All subject_type/object_type are valid Schema.org class names."""
    from pathlib import Path
    from memory_service.schema_org import SchemaOrgOntology

    jsonld_path = Path(__file__).parents[2] / "data" / "schemaorg-current-https.jsonld"
    onto = SchemaOrgOntology(jsonld_path)

    rels = await extract_relationships(LOCOMO_EXCERPT)
    assert len(rels) > 0

    for r in rels:
        for field in ("subject_type", "object_type"):
            t = r[field]
            assert t in onto._classes, (
                f"Invalid Schema.org class in {field}: {t!r} for {r}"
            )


@pytest.mark.asyncio
async def test_relationship_extraction_finds_family():
    """T2.4 — Finds parent/children relationship between Caroline and Julia."""
    rels = await extract_relationships(LOCOMO_EXCERPT)
    predicates = {r["predicate"] for r in rels}
    subjects_and_objects = {
        (r["subject_norm"], r["predicate"], r["object_norm"]) for r in rels
    }

    # Either Caroline→parent→Julia or Julia→children→Caroline (or inverse auto-stored)
    family_found = any(
        ("caroline" in s and p in ("parent", "children") and "julia" in o)
        or ("julia" in s and p in ("parent", "children") and "caroline" in o)
        for s, p, o in subjects_and_objects
    )
    assert family_found, (
        f"Expected family relationship (parent/children) between Caroline and Julia.\n"
        f"Got triples: {subjects_and_objects}\nPredicates: {predicates}"
    )


@pytest.mark.asyncio
async def test_relationship_extraction_finds_employment():
    """T2.5 — Finds worksFor relationship (Melanie → Spotify or Julia → NHS)."""
    rels = await extract_relationships(LOCOMO_EXCERPT)
    subjects_and_objects = {
        (r["subject_norm"], r["predicate"], r["object_norm"]) for r in rels
    }

    work_found = any(
        p == "worksFor" and ("melanie" in s or "julia" in s)
        for s, p, o in subjects_and_objects
    )
    assert work_found, (
        f"Expected worksFor relationship.\nGot triples: {subjects_and_objects}"
    )


@pytest.mark.asyncio
async def test_relationship_extraction_confidence_range():
    """T2.6 — Confidence values are in [0.0, 1.0]."""
    rels = await extract_relationships(LOCOMO_EXCERPT)
    for r in rels:
        assert 0.0 <= r["confidence"] <= 1.0, (
            f"Out-of-range confidence {r['confidence']} in {r}"
        )


@pytest.mark.asyncio
async def test_relationship_extraction_empty_input():
    """T2.7 — Empty or short input returns empty list without error."""
    result = await extract_relationships("")
    assert result == []

    result = await extract_relationships("Hi")
    assert result == []


# ---------------------------------------------------------------------------
# T2.8 — T2.11: Ontology summary update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ontology_update_produces_summary():
    """T2.8 — Fresh summary (no existing) is non-trivial."""
    summary = await update_ontology_summary(
        entity_name="Caroline",
        schema_type="Person",
        existing_summary="",
        new_episode_text=LOCOMO_EXCERPT,
    )
    assert isinstance(summary, str)
    assert len(summary) > 50, f"Summary too short: {summary!r}"


@pytest.mark.asyncio
async def test_ontology_update_captures_key_facts():
    """T2.9 — Summary captures Julia = nurse at NHS (LoCoMo multi-hop target)."""
    summary = await update_ontology_summary(
        entity_name="Caroline",
        schema_type="Person",
        existing_summary="",
        new_episode_text=LOCOMO_EXCERPT,
    )
    summary_lower = summary.lower()
    # Key LoCoMo fact: Julia Horrocks is Caroline's mother and a nurse
    julia_mentioned = "julia" in summary_lower or "mother" in summary_lower or "mum" in summary_lower
    assert julia_mentioned, (
        f"Expected mention of Julia (Caroline's mother) in summary.\nGot: {summary}"
    )


@pytest.mark.asyncio
async def test_ontology_update_no_hallucination():
    """T2.10 — Summary does not hallucinate facts not in the text."""
    summary = await update_ontology_summary(
        entity_name="Caroline",
        schema_type="Person",
        existing_summary="",
        new_episode_text=LOCOMO_EXCERPT,
    )
    summary_lower = summary.lower()
    # Julia is a nurse, not a doctor
    assert "doctor" not in summary_lower, (
        f"Hallucination: 'doctor' appeared in summary.\nGot: {summary}"
    )


@pytest.mark.asyncio
async def test_ontology_update_preserves_existing():
    """T2.11 — Existing summary facts are preserved when integrating new info."""
    existing = "Caroline is a Swedish woman in her early 30s living in Stockholm."
    new_text = """Session 2 — 15 June, 2023
Caroline: I just got promoted at my new job at Spotify!
"""
    summary = await update_ontology_summary(
        entity_name="Caroline",
        schema_type="Person",
        existing_summary=existing,
        new_episode_text=new_text,
    )
    summary_lower = summary.lower()
    # Old fact (Stockholm) should still be there
    assert "stockholm" in summary_lower, (
        f"Existing fact (Stockholm) lost after update.\nGot: {summary}"
    )
    # New fact (Spotify) should be integrated
    assert "spotify" in summary_lower, (
        f"New fact (Spotify) not integrated.\nGot: {summary}"
    )


@pytest.mark.asyncio
async def test_ontology_update_empty_episode():
    """T2.12 — Empty new_episode_text returns existing summary unchanged."""
    existing = "Caroline is a Swedish woman in Stockholm."
    result = await update_ontology_summary(
        entity_name="Caroline",
        schema_type="Person",
        existing_summary=existing,
        new_episode_text="",
    )
    assert result == existing


@pytest.mark.asyncio
async def test_ontology_update_julia_as_entity():
    """T2.13 — Update works for Julia Horrocks as the target entity."""
    summary = await update_ontology_summary(
        entity_name="Julia Horrocks",
        schema_type="Person",
        existing_summary="",
        new_episode_text=LOCOMO_EXCERPT,
    )
    summary_lower = summary.lower()
    # Julia is a nurse at NHS in London
    nurse_mentioned = "nurse" in summary_lower or "nhs" in summary_lower
    assert nurse_mentioned, (
        f"Expected 'nurse' or 'NHS' in Julia's summary.\nGot: {summary}"
    )
