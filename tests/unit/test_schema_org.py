"""
Phase 0 Tests — SchemaOrgOntology

Pure unit tests. No DB, no LLM. All assertions run against the bundled
schemaorg-current-https.jsonld file.

Run:
    python -m pytest tests/unit/test_schema_org.py -v
"""

import time
from pathlib import Path

import pytest

from memory_service.schema_org import SchemaOrgOntology

JSONLD_PATH = Path(__file__).parents[2] / "data" / "schemaorg-current-https.jsonld"


@pytest.fixture(scope="module")
def onto() -> SchemaOrgOntology:
    return SchemaOrgOntology(JSONLD_PATH)


# ---------------------------------------------------------------------------
# T0.0 — startup performance
# ---------------------------------------------------------------------------

def test_parse_performance():
    """JSON-LD must parse in < 5 seconds."""
    start = time.time()
    o = SchemaOrgOntology(JSONLD_PATH)
    elapsed = time.time() - start
    assert elapsed < 5.0, f"Parsing took {elapsed:.2f}s — too slow"
    assert len(o._classes) > 800
    assert len(o._properties) > 1400


# ---------------------------------------------------------------------------
# T0.1 — class hierarchy
# ---------------------------------------------------------------------------

def test_class_hierarchy_basic(onto):
    assert onto.is_subclass_of("Person", "Thing")
    assert onto.is_subclass_of("Organization", "Thing")
    assert onto.is_subclass_of("Place", "Thing")
    assert onto.is_subclass_of("Event", "Thing")


def test_class_hierarchy_deep(onto):
    # Hospital → LocalBusiness → Organization → Thing
    assert onto.is_subclass_of("Hospital", "Organization")
    assert onto.is_subclass_of("Hospital", "Thing")
    assert onto.is_subclass_of("CollegeOrUniversity", "Organization")


def test_class_hierarchy_negative(onto):
    assert not onto.is_subclass_of("Person", "Organization")
    assert not onto.is_subclass_of("Place", "Person")


def test_ancestors_person(onto):
    ancs = onto.ancestors("Person")
    assert "Person" in ancs
    assert "Thing" in ancs
    assert ancs[0] == "Person"


def test_ancestors_hospital(onto):
    ancs = onto.ancestors("Hospital")
    assert "Hospital" in ancs
    assert "Organization" in ancs
    assert "Thing" in ancs


# ---------------------------------------------------------------------------
# T0.2 — class normalization
# ---------------------------------------------------------------------------

def test_normalize_class_exact(onto):
    assert onto.normalize_class("Person") == "Person"
    assert onto.normalize_class("Organization") == "Organization"
    assert onto.normalize_class("Place") == "Place"


def test_normalize_class_case_insensitive(onto):
    assert onto.normalize_class("person") == "Person"
    assert onto.normalize_class("ORGANIZATION") == "Organization"
    assert onto.normalize_class("place") == "Place"


def test_normalize_class_aliases(onto):
    assert onto.normalize_class("company") == "Organization"
    assert onto.normalize_class("location") == "Place"
    assert onto.normalize_class("hospital") == "Hospital"
    assert onto.normalize_class("university") == "CollegeOrUniversity"


def test_normalize_class_fallback(onto):
    assert onto.normalize_class("gibberish") == "Thing"
    assert onto.normalize_class("") == "Thing"
    assert onto.normalize_class("xyz123abc") == "Thing"


# ---------------------------------------------------------------------------
# T0.3 — predicate normalization
# ---------------------------------------------------------------------------

def test_normalize_predicate_exact(onto):
    assert onto.normalize_predicate("worksFor") == "worksFor"
    assert onto.normalize_predicate("knows") == "knows"
    assert onto.normalize_predicate("parent") == "parent"
    assert onto.normalize_predicate("homeLocation") == "homeLocation"


def test_normalize_predicate_aliases(onto):
    assert onto.normalize_predicate("is-friend-of") == "knows"
    assert onto.normalize_predicate("works-at") == "worksFor"
    assert onto.normalize_predicate("works-for") == "worksFor"
    assert onto.normalize_predicate("is-mother-of") == "children"
    assert onto.normalize_predicate("is-daughter-of") == "parent"
    assert onto.normalize_predicate("lives-in") == "homeLocation"
    assert onto.normalize_predicate("born-in") == "birthPlace"
    assert onto.normalize_predicate("graduated-from") == "alumniOf"
    assert onto.normalize_predicate("member-of") == "memberOf"


def test_normalize_predicate_camel_from_hyphen(onto):
    # worksFor is already defined; test the camel conversion path
    assert onto.normalize_predicate("works-for") == "worksFor"


def test_normalize_predicate_fallback(onto):
    assert onto.normalize_predicate("gibberish-xyz") == "relatedTo"
    assert onto.normalize_predicate("") == "relatedTo"


# ---------------------------------------------------------------------------
# T0.4 — inverse properties
# ---------------------------------------------------------------------------

def test_inverse_declared_in_jsonld(onto):
    # memberOf inverseOf member (declared in JSON-LD)
    inv = onto.get_inverse("memberOf")
    assert inv == "member", f"Expected 'member', got {inv}"

    # alumniOf inverseOf alumni
    inv = onto.get_inverse("alumniOf")
    assert inv == "alumni", f"Expected 'alumni', got {inv}"

    # owns inverseOf owner
    inv = onto.get_inverse("owns")
    assert inv == "owner", f"Expected 'owner', got {inv}"


def test_inverse_manual(onto):
    # parent ↔ children (manually defined)
    assert onto.get_inverse("parent") == "children"
    assert onto.get_inverse("children") == "parent"


def test_inverse_bidirectional(onto):
    # all_inverses has both directions
    inv = onto.all_inverses
    assert inv.get("parent") == "children"
    assert inv.get("children") == "parent"


# ---------------------------------------------------------------------------
# T0.5 — symmetric detection
# ---------------------------------------------------------------------------

def test_symmetric_true(onto):
    assert onto.is_symmetric("knows") is True
    assert onto.is_symmetric("spouse") is True
    assert onto.is_symmetric("sibling") is True
    assert onto.is_symmetric("colleague") is True
    assert onto.is_symmetric("relatedTo") is True


def test_symmetric_false(onto):
    assert onto.is_symmetric("worksFor") is False
    assert onto.is_symmetric("parent") is False
    assert onto.is_symmetric("homeLocation") is False
    assert onto.is_symmetric("memberOf") is False


# ---------------------------------------------------------------------------
# T0.6 — domain/range validation
# ---------------------------------------------------------------------------

def test_validate_triple_valid(onto):
    assert onto.validate_triple("Person", "worksFor", "Organization") is True
    assert onto.validate_triple("Person", "knows", "Person") is True
    assert onto.validate_triple("Person", "homeLocation", "Place") is True
    assert onto.validate_triple("Person", "parent", "Person") is True


def test_validate_triple_subclass_ok(onto):
    # Hospital is subClassOf Organization — worksFor range=Organization should accept Hospital
    assert onto.validate_triple("Person", "worksFor", "Hospital") is True
    # CollegeOrUniversity is subClassOf Organization
    assert onto.validate_triple("Person", "alumniOf", "CollegeOrUniversity") is True


def test_validate_triple_invalid_domain(onto):
    assert onto.validate_triple("Place", "worksFor", "Organization") is False


def test_validate_triple_invalid_range(onto):
    assert onto.validate_triple("Person", "worksFor", "Place") is False


def test_validate_triple_unknown_predicate(onto):
    assert onto.validate_triple("Person", "nonExistentPred", "Organization") is False


# ---------------------------------------------------------------------------
# T0.7 — prompt reference
# ---------------------------------------------------------------------------

def test_prompt_reference_non_empty(onto):
    ref = onto.prompt_reference
    assert len(ref) > 10_000, f"Prompt reference too short: {len(ref)} chars"


def test_prompt_reference_contains_key_classes(onto):
    ref = onto.prompt_reference
    for cls in ["Person", "Organization", "Place", "Event", "Product"]:
        assert cls in ref, f"Missing class: {cls}"


def test_prompt_reference_contains_key_predicates(onto):
    ref = onto.prompt_reference
    for pred in ["worksFor", "knows", "parent", "homeLocation", "memberOf"]:
        assert pred in ref, f"Missing predicate: {pred}"


def test_prompt_reference_cached(onto):
    """prompt_reference is a cached_property — same object returned twice."""
    ref1 = onto.prompt_reference
    ref2 = onto.prompt_reference
    assert ref1 is ref2


def test_prompt_reference_has_sections(onto):
    ref = onto.prompt_reference
    assert "## Schema.org Classes" in ref
    assert "## Schema.org Properties" in ref
