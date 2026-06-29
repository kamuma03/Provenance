"""Domain registry — domains are data, not code (R15, R49).

P0 ships the *shape* and the tier assignment (Appendix A). Full extraction schemas
(entity Pydantic models, prompts) are filled per domain in P1+. Adding/promoting a
domain is a registry edit only (R48, R50).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class DomainTier(StrEnum):
    BUILT = "built"  # golden-set + eval-gated
    REGISTRY_READY = "registry_ready"  # schema defined, detector-routable, not gated
    ROADMAP = "roadmap"  # named, sketched, not built


class DomainSpec(BaseModel):
    """One registry entry. `description` is what the detector matches against (R8)."""

    id: str
    name: str
    description: str
    tier: DomainTier
    entity_types: list[str] = Field(default_factory=list)
    relation_types: list[str] = Field(default_factory=list)
    # extraction_schema is attached in P1+ (kept out of the P0 shape on purpose).


# The P0 catalog shape (Appendix A). Relation/entity lists are the agreed v1 types;
# the generic fallback uses an open predicate and is non-traversable by type.
REGISTRY: dict[str, DomainSpec] = {
    "sec_financial": DomainSpec(
        id="sec_financial",
        name="SEC Financial",
        description="SEC filings (10-K/10-Q): companies, subsidiaries, officers, risk factors.",
        tier=DomainTier.BUILT,
        entity_types=[
            "Company", "Subsidiary", "Person", "RiskFactor",
            "FinancialMetric", "FiscalPeriod", "Auditor", "LegalProceeding",
        ],
        relation_types=[
            "OWNS_SUBSIDIARY", "HAS_OFFICER", "CITES_RISK",
            "REPORTED_METRIC", "AUDITED_BY", "PARTY_TO",
        ],
    ),
    "research_papers": DomainSpec(
        id="research_papers",
        name="Research Papers",
        description="Academic papers: authors, methods, datasets, findings, citations.",
        tier=DomainTier.BUILT,
        entity_types=["Paper", "Author", "Institution", "Method", "Dataset", "Finding", "Venue"],
        relation_types=[
            "AUTHORED_BY", "AFFILIATED_WITH", "USES_METHOD",
            "EVALUATES_ON", "REPORTS_FINDING", "CITES", "PUBLISHED_IN",
        ],
    ),
    "legal_contracts": DomainSpec(
        id="legal_contracts",
        name="Legal / Contracts",
        description="Contracts: parties, clauses, obligations, governing law, amendments.",
        tier=DomainTier.BUILT,
        entity_types=[
            "Party", "Contract", "Clause", "Obligation",
            "Term", "GoverningLaw", "Signatory", "Amendment",
        ],
        relation_types=[
            "PARTY_TO", "CONTAINS_CLAUSE", "IMPOSES_OBLIGATION",
            "GOVERNED_BY", "AMENDS", "EFFECTIVE_ON", "SIGNED_BY",
        ],
    ),
    "technical_software": DomainSpec(
        id="technical_software",
        name="Technical / Software docs",
        description="Software/API docs: components, endpoints, dependencies, versions, errors.",
        tier=DomainTier.BUILT,
        entity_types=["Component", "API", "Parameter", "Dependency", "Version", "ErrorCode"],
        relation_types=["DEPENDS_ON", "EXPOSES", "DEPRECATES", "INTRODUCED_IN", "RAISES"],
    ),
    "generic": DomainSpec(
        id="generic",
        name="Generic (fallback)",
        description="Out-of-domain / low-confidence fallback. Open predicate, not traversable.",
        tier=DomainTier.BUILT,
        entity_types=["Person", "Organization", "Location", "Date", "Event", "Concept"],
        relation_types=["RELATES_TO", "MENTIONS"],
    ),
    "biomedical_clinical": DomainSpec(
        id="biomedical_clinical",
        name="Biomedical / Clinical",
        description="Biomedical literature + drug labels: drugs, conditions, genes, trials.",
        tier=DomainTier.REGISTRY_READY,
        entity_types=[
            "Drug", "Condition", "Gene", "ClinicalTrial", "Dosage", "AdverseEvent", "Population",
        ],
        relation_types=[
            "TREATS", "INTERACTS_WITH", "CONTRAINDICATED_FOR",
            "TARGETS", "CAUSES_AE", "STUDIED_IN",
        ],
    ),
    "regulatory_standards": DomainSpec(
        id="regulatory_standards",
        name="Regulatory / Standards",
        description="Regulations/standards (GDPR/NIST/ISO): articles, requirements, authorities.",
        tier=DomainTier.REGISTRY_READY,
        entity_types=[
            "Regulation", "Article", "Requirement", "Authority", "Definition", "Penalty", "Scope",
        ],
        relation_types=[
            "CONTAINS_ARTICLE", "REFERENCES", "IMPOSES_REQUIREMENT",
            "ISSUED_BY", "DEFINES", "PENALIZES", "APPLIES_TO",
        ],
    ),
    "patents": DomainSpec(
        id="patents",
        name="Patents",
        description="Patent documents: inventors, assignees, claims, prior art, classifications.",
        tier=DomainTier.REGISTRY_READY,
        entity_types=["Patent", "Inventor", "Assignee", "Claim", "PriorArt", "Classification"],
        relation_types=[
            "INVENTED_BY", "ASSIGNED_TO", "HAS_CLAIM", "CITES_PRIOR_ART", "CLASSIFIED_AS",
        ],
    ),
}

GENERIC_FALLBACK_ID = "generic"
