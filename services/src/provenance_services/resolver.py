"""v1 entity resolution (R18/R19).

Co-reference is resolved by normalized-string match on (type, canonical_name). Entity
ids are a deterministic hash of (kb_id, type, normalized_name), so the *same* real-world
entity gets the *same* id across documents — merge is automatic and the graph densifies
as a KB grows (R19). v2 (embedding blocking + LLM adjudication) is deferred.

Lives with the Graph service and is reused by query-time entity linking (R26).
"""

from __future__ import annotations

import hashlib
import re

from provenance_contracts import Entity, EntityCandidate
from pydantic import BaseModel

_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")
_ORG_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "ltd", "limited", "llc", "plc", "co"}


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation, drop leading 'the' and trailing org suffixes."""
    s = _PUNCT.sub(" ", name.lower())
    s = _WS.sub(" ", s).strip()
    tokens = s.split()
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    while tokens and tokens[-1] in _ORG_SUFFIXES:
        tokens = tokens[:-1]
    return " ".join(tokens)


def entity_id(kb_id: str, type_: str, normalized: str) -> str:
    digest = hashlib.sha1(f"{kb_id}|{type_}|{normalized}".encode()).hexdigest()
    return f"ent_{digest[:12]}"


class ResolutionResult(BaseModel):
    entities: list[Entity]  # de-duplicated, with stable ids
    name_to_id: dict[str, str]  # candidate canonical_name -> entity id (for relations)
    created: int
    merged: int


class EntityResolver:
    """Resolve candidates to stable ids, merging co-referents (R18)."""

    def resolve(
        self,
        kb_id: str,
        candidates: list[EntityCandidate],
        known_ids: set[str] | None = None,
    ) -> ResolutionResult:
        known = known_ids or set()
        by_id: dict[str, Entity] = {}
        name_to_id: dict[str, str] = {}
        created = 0
        merged = 0
        for c in candidates:
            norm = normalize_name(c.canonical_name)
            eid = entity_id(kb_id, c.type, norm)
            name_to_id[c.canonical_name] = eid
            # Also key by the normalized form so a relation endpoint that drifted in surface
            # form ("Acme Robotics" vs "Acme Robotics Inc") still resolves (review M-7).
            name_to_id.setdefault(norm, eid)
            if eid in by_id:
                continue  # already produced this batch
            if eid in known:
                merged += 1
            else:
                created += 1
            by_id[eid] = Entity(id=eid, kb_id=kb_id, type=c.type, canonical_name=c.canonical_name)
        return ResolutionResult(
            entities=list(by_id.values()),
            name_to_id=name_to_id,
            created=created,
            merged=merged,
        )
