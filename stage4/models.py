from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class CoverageStatus(StrEnum):
    FULL = "FULL"
    DEGRADED = "DEGRADED"
    INSUFFICIENT = "INSUFFICIENT"


class EventStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DEFERRED_VERSION_CHANGED = "DEFERRED_VERSION_CHANGED"


class RelationType(StrEnum):
    DIRECT = "DIRECT"
    THEMATIC = "THEMATIC"
    INDIRECT = "INDIRECT"


@dataclass(frozen=True)
class SourceEvidence:
    source_ref: str
    source_name: str
    source_class: str
    independence_group: str
    url: str = ""


@dataclass(frozen=True)
class BrokerPosition:
    broker: str
    ticker: str
    declared_weight_pct: float


@dataclass(frozen=True)
class BrokerPortfolio:
    broker: str
    positions: tuple[BrokerPosition, ...]


@dataclass(frozen=True)
class PortfolioSnapshot:
    version: str
    brokers: dict[str, BrokerPortfolio]
    source_format: str
    freshness_status: str
    warnings: tuple[str, ...] = ()

    def broker_weight(self, broker: str, ticker: str) -> float | None:
        portfolio = self.brokers.get(broker)
        if portfolio is None:
            return None
        for position in portfolio.positions:
            if position.ticker == ticker:
                return position.declared_weight_pct
        return None


@dataclass(frozen=True)
class NormalizedNews:
    source_ref: str
    source_name: str
    source_class: str
    independence_group: str
    title: str
    summary: str
    url: str
    published_at: datetime
    ingested_at: datetime
    effective_at: datetime | None
    updated_at: datetime | None
    material_update: bool
    content_kind: str
    event_type: str
    entity_ids: tuple[str, ...]
    effective_key: str
    key_facts: dict[str, Any]
    direction: str
    stable_event_id: str | None = None
    numerical_claims: tuple[dict[str, Any], ...] = ()


@dataclass
class CanonicalEvent:
    event_id: str
    event_version: int
    event_type: str
    entity_ids: tuple[str, ...]
    effective_key: str
    key_facts: dict[str, Any]
    direction: str
    status: EventStatus
    accepted: bool
    confirmed: bool
    sources: tuple[SourceEvidence, ...]
    source_published_at: datetime
    ingested_at: datetime
    effective_at: datetime | None = None
    updated_at: datetime | None = None
    material_update: bool = False
    numerical_claims: tuple[dict[str, Any], ...] = ()
    broker_relations: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    attention_state: str = "FACT_ONLY"
    warnings: list[str] = field(default_factory=list)

    @property
    def event_time(self) -> datetime:
        return self.effective_at or self.source_published_at


@dataclass(frozen=True)
class CoverageAssessment:
    status: CoverageStatus
    runtime_status: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class DayDecision:
    action: str
    headline: str
    rationale: str
    coverage_status: CoverageStatus
    accepted_event_ids: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotManifest:
    snapshot_id: str
    window_start: datetime
    event_cutoff_at: datetime
    snapshot_freeze_at: datetime
    portfolio_config_version: str
    watchlist_config_version: str
    rules_version: str
    source_catalog_version: str
    event_refs: tuple[str, ...]
    config_snapshot_id: str
    manifest_hash: str


@dataclass(frozen=True)
class GroundedExplanation:
    event_id: str
    event_version: int
    summary: str
    source_refs: tuple[str, ...]
    fact_refs: tuple[str, ...]
    used_fallback: bool = False
