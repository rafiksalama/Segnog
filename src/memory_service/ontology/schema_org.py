"""
SchemaOrgOntology — full Schema.org JSON-LD reference implementation.

Parsed once at startup. Provides:
- normalize_class() / normalize_predicate()  — canonicalize LLM output
- get_inverse() / is_symmetric()             — ontological inference
- validate_triple()                          — domain/range check
- ancestors()                                — class hierarchy walk
- prompt_reference()                         — full compact text for LLM prompts (cached)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Class embedding helpers (live here to avoid circular imports with intelligence/)
# ---------------------------------------------------------------------------

# Non-entity Schema.org class families excluded from the retrieval index.
# Actions describe behaviors; Enumerations are vocabulary values.
_EXCLUDED_PARENTS = {"Action", "Enumeration", "StructuredValue", "DataType"}


def _is_excluded(name: str, onto: SchemaOrgOntology) -> bool:  # type: ignore[name-defined]
    """Return True if the class or any of its ancestors is in _EXCLUDED_PARENTS."""
    visited: set[str] = set()
    queue = [name]
    while queue:
        current = queue.pop()
        if current in visited:
            continue
        visited.add(current)
        if current in _EXCLUDED_PARENTS:
            return True
        info = onto._classes.get(current)
        if info:
            queue.extend(info.parents)
    return False


def _cache_path(jsonld_path: Path) -> Path:
    """Return the disk-cache path for class embeddings alongside the schema file."""
    from ..config import get_embedding_model

    model_slug = get_embedding_model().replace("/", "_").replace(":", "_")
    return jsonld_path.parent / f"class_embeddings_{model_slug}.json"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ClassInfo:
    name: str  # "Person"
    uri: str  # "schema:Person"
    parents: List[str] = field(default_factory=list)  # ["Thing"]
    comment: str = ""


@dataclass
class PropertyInfo:
    name: str  # "worksFor"
    uri: str  # "schema:worksFor"
    domain: List[str] = field(default_factory=list)  # ["Person"]
    range: List[str] = field(default_factory=list)  # ["Organization"]
    inverse_of: Optional[str] = None  # "employees"
    comment: str = ""


# ---------------------------------------------------------------------------
# Alias maps  (common non-canonical → canonical Schema.org names)
# These cover the most frequent LLM mis-namings.
# ---------------------------------------------------------------------------

_CLASS_ALIASES: Dict[str, str] = {
    # case / spacing variants handled by normalize_class() first,
    # so these are semantic aliases only
    "company": "Organization",
    "corporation": "Corporation",
    "firm": "Organization",
    "business": "LocalBusiness",
    "store": "Store",
    "shop": "Store",
    "hospital": "Hospital",
    "school": "School",
    "university": "CollegeOrUniversity",
    "college": "CollegeOrUniversity",
    "location": "Place",
    "city": "City",
    "country": "Country",
    "region": "AdministrativeArea",
    "address": "PostalAddress",
    "human": "Person",
    "individual": "Person",
    "character": "Person",
    "movie": "Movie",
    "film": "Movie",
    "book": "Book",
    "song": "MusicRecording",
    "album": "MusicAlbum",
    "article": "Article",
    "website": "WebSite",
    "webpage": "WebPage",
    "job": "JobPosting",
    "disease": "MedicalCondition",
    "drug": "Drug",
    "award": "Award",
    "course": "Course",
    "recipe": "Recipe",
    "vehicle": "Vehicle",
    "car": "Car",
    "language": "Language",
    # Animals / Pets
    "animal": "Animal",
    "pet": "Animal",
    "dog": "Animal",
    "cat": "Animal",
    "bird": "Animal",
    "horse": "Animal",
    "rabbit": "Animal",
    "fish": "Animal",
}

_PREDICATE_ALIASES: Dict[str, str] = {
    # legacy hyphenated forms
    "is-friend-of": "knows",
    "friend-of": "knows",
    "friends-with": "knows",
    "knows-person": "knows",
    "works-at": "worksFor",
    "works-for": "worksFor",
    "employed-at": "worksFor",
    "employed-by": "worksFor",
    "is-employed-at": "worksFor",
    "is-employed-by": "worksFor",
    "works-with": "colleague",
    "is-colleague-of": "colleague",
    "is-mother-of": "children",
    "is-father-of": "children",
    "is-parent-of": "children",
    "has-child": "children",
    "has-daughter": "children",
    "has-son": "children",
    "is-daughter-of": "parent",
    "is-son-of": "parent",
    "is-child-of": "parent",
    "mother-of": "children",
    "father-of": "children",
    "daughter-of": "parent",
    "son-of": "parent",
    "child-of": "parent",
    "married-to": "spouse",
    "is-married-to": "spouse",
    "is-sibling-of": "sibling",
    "sibling-of": "sibling",
    "is-related-to": "relatedTo",
    "related-to": "relatedTo",
    "lives-in": "homeLocation",
    "located-in": "homeLocation",
    "based-in": "homeLocation",
    "resides-in": "homeLocation",
    "born-in": "birthPlace",
    "from": "birthPlace",
    "nationality": "nationality",
    "is-from": "birthPlace",
    "member-of": "memberOf",
    "belongs-to": "memberOf",
    "part-of": "memberOf",
    "graduated-from": "alumniOf",
    "attended": "alumniOf",
    "studied-at": "alumniOf",
    "founded": "founder",
    "founded-by": "founder",
    "owns": "owns",
    "owned-by": "owner",
    "has-affiliation": "affiliation",
    "affiliated-with": "affiliation",
    "located-at": "location",
    "has-location": "location",
}

# Predicates that are symmetric by convention (not always declared via inverseOf in Schema.org)
_SYMMETRIC_PREDICATES: Set[str] = {
    "knows",
    "colleague",
    "spouse",
    "sibling",
    "relatedTo",
}

# Manually-defined inverse pairs (where Schema.org JSON-LD doesn't declare inverseOf)
_MANUAL_INVERSES: Dict[str, str] = {
    "parent": "children",
    "children": "parent",
}


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class SchemaOrgOntology:
    """
    Loads and parses the full Schema.org JSON-LD at construction time.
    Thread-safe after construction — all state is read-only.
    """

    def __init__(self, jsonld_path: str | Path):
        path = Path(jsonld_path)
        if not path.exists():
            raise FileNotFoundError(f"Schema.org JSON-LD not found: {path}")

        self._jsonld_path = path  # kept for disk-cache path derivation

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        graph = data.get("@graph", [])

        # Index classes and properties (schema: namespace only)
        self._classes: Dict[str, ClassInfo] = {}
        self._properties: Dict[str, PropertyInfo] = {}
        self._inverses: Dict[str, str] = dict(_MANUAL_INVERSES)
        # Populated lazily by embed_classes(); None until first call
        self._class_embeddings: Optional[Dict[str, List[float]]] = None

        for entry in graph:
            entry_id = entry.get("@id", "")
            if not entry_id.startswith("schema:"):
                continue

            types = entry.get("@type", [])
            if isinstance(types, str):
                types = [types]

            name = entry_id[len("schema:") :]

            if "rdfs:Class" in types:
                parents = self._extract_ids(entry.get("rdfs:subClassOf", []))
                # keep only schema: parents
                parents = [p[len("schema:") :] for p in parents if p.startswith("schema:")]
                self._classes[name] = ClassInfo(
                    name=name,
                    uri=entry_id,
                    parents=parents,
                    comment=self._extract_label(entry.get("rdfs:comment", "")),
                )

            elif "rdf:Property" in types:
                domain = [
                    d[len("schema:") :]
                    for d in self._extract_ids(entry.get("schema:domainIncludes", []))
                    if d.startswith("schema:")
                ]
                range_ = [
                    r[len("schema:") :]
                    for r in self._extract_ids(entry.get("schema:rangeIncludes", []))
                    if r.startswith("schema:")
                ]
                inverse_raw = entry.get("schema:inverseOf")
                inverse_name: Optional[str] = None
                if inverse_raw:
                    inv_id = (
                        inverse_raw.get("@id") if isinstance(inverse_raw, dict) else None
                    ) or ""
                    if inv_id.startswith("schema:"):
                        inverse_name = inv_id[len("schema:") :]

                self._properties[name] = PropertyInfo(
                    name=name,
                    uri=entry_id,
                    domain=domain,
                    range=range_,
                    inverse_of=inverse_name,
                    comment=self._extract_label(entry.get("rdfs:comment", "")),
                )

                if inverse_name:
                    self._inverses[name] = inverse_name

        # Build lowercase → canonical name indexes for fast normalization
        self._class_lower: Dict[str, str] = {k.lower(): k for k in self._classes}
        self._prop_lower: Dict[str, str] = {k.lower(): k for k in self._properties}

        logger.info(
            "SchemaOrgOntology loaded: %d classes, %d properties, %d inverse pairs",
            len(self._classes),
            len(self._properties),
            len(self._inverses),
        )

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_ids(val) -> List[str]:
        """Extract @id strings from a scalar, dict, or list."""
        if not val:
            return []
        if isinstance(val, str):
            return [val]
        if isinstance(val, dict):
            return [val["@id"]] if "@id" in val else []
        if isinstance(val, list):
            result = []
            for item in val:
                if isinstance(item, dict) and "@id" in item:
                    result.append(item["@id"])
                elif isinstance(item, str):
                    result.append(item)
            return result
        return []

    @staticmethod
    def _extract_label(val) -> str:
        if isinstance(val, dict):
            return val.get("@value", "")
        return str(val) if val else ""

    # ------------------------------------------------------------------
    # Class API
    # ------------------------------------------------------------------

    def get_class(self, name: str) -> Optional[ClassInfo]:
        return self._classes.get(name)

    def ancestors(self, class_name: str) -> List[str]:
        """Return [class_name, parent, grandparent, …] up to Thing."""
        result: List[str] = []
        visited: Set[str] = set()
        queue = [class_name]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            result.append(current)
            info = self._classes.get(current)
            if info:
                queue.extend(info.parents)
        return result

    def is_subclass_of(self, child: str, parent: str) -> bool:
        return parent in self.ancestors(child)

    def normalize_class(self, raw: str) -> str:
        """
        Map any raw string to a canonical Schema.org class name.
        Fallback: 'Thing'.
        """
        if not raw:
            return "Thing"
        # 1. Try exact match
        if raw in self._classes:
            return raw
        # 2. Try lowercase match
        lower = raw.lower()
        if lower in self._class_lower:
            return self._class_lower[lower]
        # 3. Try alias map
        alias = _CLASS_ALIASES.get(lower)
        if alias and alias in self._classes:
            return alias
        # 4. Try stripping non-alphanumeric and retry
        cleaned = re.sub(r"[^a-zA-Z0-9]", "", raw)
        if cleaned in self._classes:
            return cleaned
        if cleaned.lower() in self._class_lower:
            return self._class_lower[cleaned.lower()]
        return "Thing"

    # ------------------------------------------------------------------
    # Property API
    # ------------------------------------------------------------------

    def get_property(self, name: str) -> Optional[PropertyInfo]:
        return self._properties.get(name)

    def get_inverse(self, predicate: str) -> Optional[str]:
        """Return the Schema.org inverse predicate name, if any."""
        return self._inverses.get(predicate)

    def is_symmetric(self, predicate: str) -> bool:
        """
        True if predicate is symmetric (A→B implies B→A).
        Covers explicit symmetrics (knows, spouse…) and schema:inverseOf self-references.
        """
        if predicate in _SYMMETRIC_PREDICATES:
            return True
        inv = self._inverses.get(predicate)
        return inv == predicate  # inverseOf points to self

    def validate_triple(self, subj_type: str, predicate: str, obj_type: str) -> bool:
        """
        Return True if predicate domain includes subj_type (or a superclass)
        and range includes obj_type (or a superclass).
        Returns True if domain/range are not specified (unconstrained).
        """
        prop = self._properties.get(predicate)
        if not prop:
            return False

        subj_ancestors = set(self.ancestors(subj_type))
        obj_ancestors = set(self.ancestors(obj_type))

        if prop.domain:
            if not any(d in subj_ancestors for d in prop.domain):
                return False
        if prop.range:
            if not any(r in obj_ancestors for r in prop.range):
                return False
        return True

    def normalize_predicate(self, raw: str) -> str:
        """
        Map any raw string to a canonical Schema.org property name.
        Fallback: 'relatedTo'.
        """
        if not raw:
            return "relatedTo"
        # 1. Exact match
        if raw in self._properties:
            return raw
        # 2. Lowercase match
        lower = raw.lower()
        if lower in self._prop_lower:
            return self._prop_lower[lower]
        # 3. Alias map (hyphenated legacy forms)
        alias = _PREDICATE_ALIASES.get(lower)
        if alias and alias in self._properties:
            return alias
        # 4. camelCase from hyphenated: "works-for" → "worksFor"
        camel = re.sub(r"-([a-z])", lambda m: m.group(1).upper(), raw)
        if camel in self._properties:
            return camel
        if camel.lower() in self._prop_lower:
            return self._prop_lower[camel.lower()]
        return "relatedTo"

    # ------------------------------------------------------------------
    # Prompt reference (cached — built once, reused forever)
    # ------------------------------------------------------------------

    def prompt_for_classes(self, names: List[str]) -> str:
        """Return a compact prompt snippet for the specified Schema.org class names.

        Useful for injecting a curated subset rather than the full 930-class list.
        """
        lines = ["Entity types (Schema.org classes):"]
        for name in names:
            info = self._classes.get(name)
            if info:
                parent_str = f"({','.join(info.parents)})" if info.parents else ""
                comment_str = f" — {info.comment[:80]}" if info.comment else ""
                lines.append(f"  {name}{parent_str}{comment_str}")
            else:
                lines.append(f"  {name}")
        return "\n".join(lines)

    def prompt_for_predicates(self, names: List[str]) -> str:
        """Return a compact prompt snippet for the specified Schema.org property names.

        Useful for injecting a curated subset rather than the full 1520-property list.
        """
        lines = ["Relationship predicates (Schema.org properties):"]
        for name in names:
            prop = self._properties.get(name)
            if prop:
                domain_str = "/".join(prop.domain) if prop.domain else "?"
                range_str = "/".join(prop.range) if prop.range else "?"
                inv_str = f", inverse={prop.inverse_of}" if prop.inverse_of else ""
                sym_str = ", symmetric" if self.is_symmetric(name) else ""
                comment_str = f" — {prop.comment[:60]}" if prop.comment else ""
                lines.append(
                    f"  {name}  domain={domain_str}  range={range_str}"
                    f"{inv_str}{sym_str}{comment_str}"
                )
            else:
                lines.append(f"  {name}")
        return "\n".join(lines)

    @cached_property
    def prompt_reference(self) -> str:
        """
        Full compact Schema.org reference text for LLM prompts.
        Cached after first access. ~26K tokens.

        Format:
          CLASSES (930):
            Person(Thing) — A person (alive, dead, undead, or fictional).
            Organization(Thing) — An organization such as a school, NGO, corporation, club, etc.
            ...
          PROPERTIES (1520):
            worksFor  domain=Person  range=Organization — Organizations that the person works for.
            ...
        """
        lines: List[str] = []

        # --- Classes ---
        lines.append(f"## Schema.org Classes ({len(self._classes)} total)")
        lines.append(
            "Format: ClassName(ParentClass) — description\n"
            "Use the exact ClassName when naming entity types.\n"
        )
        for name in sorted(self._classes):
            info = self._classes[name]
            parent_str = f"({','.join(info.parents)})" if info.parents else ""
            comment_str = f" — {info.comment[:100]}" if info.comment else ""
            lines.append(f"  {name}{parent_str}{comment_str}")

        lines.append("")

        # --- Properties ---
        lines.append(f"## Schema.org Properties ({len(self._properties)} total)")
        lines.append(
            "Format: propertyName  domain=X  range=Y  [inverse=Z] — description\n"
            "Use the exact propertyName (camelCase) when naming predicates.\n"
        )
        for name in sorted(self._properties):
            prop = self._properties[name]
            parts = [f"  {name}"]
            if prop.domain:
                parts.append(f"domain={','.join(prop.domain)}")
            if prop.range:
                parts.append(f"range={','.join(prop.range)}")
            if prop.inverse_of:
                parts.append(f"inverse={prop.inverse_of}")
            if name in _SYMMETRIC_PREDICATES:
                parts.append("symmetric")
            if prop.comment:
                parts.append(f"— {prop.comment[:80]}")
            lines.append("  ".join(parts))

        return "\n".join(lines)

    @cached_property
    def symmetric_predicates(self) -> Set[str]:
        """All symmetric predicates (built-in + inverseOf-self)."""
        result = set(_SYMMETRIC_PREDICATES)
        for name, inv in self._inverses.items():
            if inv == name:
                result.add(name)
        return result

    @cached_property
    def all_inverses(self) -> Dict[str, str]:
        """All inverse predicate pairs (both directions)."""
        both: Dict[str, str] = dict(self._inverses)
        for k, v in list(self._inverses.items()):
            if v not in both:
                both[v] = k
        return both

    async def embed_classes(self, embed_fn) -> Dict[str, List[float]]:
        """
        Return embeddings for all indexable Schema.org class descriptions.

        Load order:
          1. In-process cache (self._class_embeddings) — instant
          2. Disk cache next to the JSON-LD file — fast (no API calls)
          3. Compute via embed_fn, then save to disk — one-time cost

        Action and Enumeration subtypes are excluded (not extractable entities).

        Args:
            embed_fn: async callable (text: str) -> List[float]
        """
        if self._class_embeddings is not None:
            return self._class_embeddings

        import asyncio

        cache_file = _cache_path(self._jsonld_path)

        # --- Try disk cache first ---
        if cache_file.exists():
            try:
                with open(cache_file, encoding="utf-8") as f:
                    self._class_embeddings = json.load(f)
                logger.info(
                    "SchemaOrgOntology: loaded %d class embeddings from disk cache",
                    len(self._class_embeddings),
                )
                return self._class_embeddings
            except Exception as e:
                logger.warning("SchemaOrgOntology: disk cache load failed (%s), recomputing", e)

        # --- Compute embeddings ---
        indexable = {
            name: (
                f"{name}"
                + (f" ({','.join(info.parents)})" if info.parents else "")
                + (f": {info.comment}" if info.comment else "")
            )
            for name, info in self._classes.items()
            if not _is_excluded(name, self)
        }

        logger.info(
            "SchemaOrgOntology: computing embeddings for %d indexable classes (of %d total)…",
            len(indexable),
            len(self._classes),
        )

        # Sequential batches, each batch runs concurrently (throttled by semaphore in embed_fn)
        items = list(indexable.items())
        batch_size = 20
        embeddings: Dict[str, List[float]] = {}
        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]
            try:
                vectors = await asyncio.gather(*[embed_fn(text) for _, text in batch])
                for (name, _), vec in zip(batch, vectors):
                    embeddings[name] = vec
                logger.debug("SchemaOrgOntology: embedded %d/%d classes", i + len(batch), len(items))
            except Exception as e:
                logger.error(
                    "SchemaOrgOntology: embedding computation failed at batch %d/%d: %s",
                    i // batch_size + 1, (len(items) + batch_size - 1) // batch_size,
                    e,
                )
                # Continue with what we have so far
                break

        # --- Save to disk cache ---
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(embeddings, f)
            logger.info(
                "SchemaOrgOntology: saved %d class embeddings to %s", len(embeddings), cache_file
            )
        except Exception as e:
            logger.warning("SchemaOrgOntology: could not save disk cache: %s", e)

        if not embeddings:
            logger.error(
                "SchemaOrgOntology: computed 0/%d class embeddings — entity extraction disabled",
                len(indexable),
            )

        self._class_embeddings = embeddings or {}
        return self._class_embeddings


# ---------------------------------------------------------------------------
# Process-level shared singleton (avoids double-loading the 5-15 MB JSON-LD)
# ---------------------------------------------------------------------------

_shared_instance: Optional["SchemaOrgOntology"] = None


def _find_jsonld() -> "Path":
    """Locate schemaorg-current-https.jsonld, working in both local-dev and
    installed-package (Docker) environments."""
    from pathlib import Path as _Path
    import os

    # 1. Explicit env override
    env = os.getenv("SCHEMA_ORG_JSONLD_PATH")
    if env and _Path(env).exists():
        return _Path(env)

    # 2. Bundled inside the installed package (importlib.resources, Python 3.9+)
    try:
        import importlib.resources as _pkg

        ref = _pkg.files("memory_service.data") / "schemaorg-current-https.jsonld"
        p = _Path(str(ref))
        if p.exists():
            return p
    except Exception:
        pass

    # 3. Walk up from this file — works for local development
    current = _Path(__file__).parent
    for _ in range(5):
        candidate = current / "data" / "schemaorg-current-https.jsonld"
        if candidate.exists():
            return candidate
        current = current.parent

    raise FileNotFoundError("schemaorg-current-https.jsonld not found in any search path")


def get_shared_ontology(jsonld_path: Optional[str] = None) -> "SchemaOrgOntology":
    """Return (or create) the process-level SchemaOrgOntology singleton.

    The first caller may pass ``jsonld_path``; subsequent calls ignore it and
    return the already-loaded instance.  This prevents the JSON-LD from being
    parsed multiple times when several smart modules import this function.
    """
    global _shared_instance
    if _shared_instance is None:
        from pathlib import Path as _Path

        path = _Path(jsonld_path) if jsonld_path else _find_jsonld()
        _shared_instance = SchemaOrgOntology(path)
    return _shared_instance
