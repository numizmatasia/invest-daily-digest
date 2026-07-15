from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from infra.event_store import EventStoreService
from infra.types import sha256_json
from stage4.models import CanonicalEvent, EventStatus, NormalizedNews, SourceEvidence


_OFFICIAL_CLASSES = {"OFFICIAL", "REGULATOR", "EXCHANGE"}
_RELIABLE_CLASSES = _OFFICIAL_CLASSES | {"TIER_1", "TIER_2"}
_SINGLE_SOURCE_CONFIRMERS = {"REUTERS", "BLOOMBERG", "AP", "ASSOCIATED PRESS", "FINANCIAL TIMES", "FT", "WALL STREET JOURNAL", "WSJ"}


def _event_id(item: NormalizedNews) -> str:
    if item.stable_event_id:
        return item.stable_event_id
    return EventStoreService.build_event_id(
        entity_ids=item.entity_ids,
        event_type=item.event_type,
        effective_key=item.effective_key,
        key_facts=item.key_facts.get("identity", {}),
    )


def _confirmed(items: list[NormalizedNews]) -> bool:
    if any(item.source_class in _OFFICIAL_CLASSES for item in items):
        return True
    if any(
        item.source_class in _RELIABLE_CLASSES
        and item.source_name.strip().upper() in _SINGLE_SOURCE_CONFIRMERS
        for item in items
    ):
        return True
    independent = {
        item.independence_group
        for item in items
        if item.source_class in _RELIABLE_CLASSES
    }
    return len(independent) >= 2


def _merge_claims(items: list[NormalizedNews], valid_refs: set[str]) -> tuple[dict, ...]:
    output: list[dict] = []
    seen: set[str] = set()
    for item in items:
        for claim in item.numerical_claims:
            source_ref = str(claim.get("source_ref", ""))
            if source_ref not in valid_refs:
                continue
            fingerprint = sha256_json(claim)
            if fingerprint not in seen:
                seen.add(fingerprint)
                output.append(dict(claim))
    return tuple(output)


def build_events(items: Iterable[NormalizedNews], repository) -> list[CanonicalEvent]:
    if repository is None:
        raise RuntimeError("STATE_STORE_REQUIRED")
    groups: dict[str, list[NormalizedNews]] = defaultdict(list)
    for item in items:
        groups[_event_id(item)].append(item)

    service = EventStoreService(repository)
    events: list[CanonicalEvent] = []
    for event_id, group in groups.items():
        group.sort(key=lambda item: (item.ingested_at, item.source_ref))
        latest = group[-1]
        version = 0
        for item in group:
            item_payload = {
                "event_type": item.event_type,
                "entity_ids": list(item.entity_ids),
                "effective_key": item.effective_key,
                "key_facts": item.key_facts,
                "direction": item.direction,
                "effective_at": item.effective_at.isoformat() if item.effective_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "material_update": item.material_update,
            }
            version, _ = service.upsert(
                event_id=event_id,
                event_type=item.event_type,
                canonical_payload=item_payload,
                source_ref=item.source_ref,
                now=item.ingested_at,
            )
        valid_refs = {item.source_ref for item in group}
        sources_by_ref: dict[str, SourceEvidence] = {}
        for item in group:
            sources_by_ref.setdefault(
                item.source_ref,
                SourceEvidence(
                    source_ref=item.source_ref,
                    source_name=item.source_name,
                    source_class=item.source_class,
                    independence_group=item.independence_group,
                    url=item.url,
                ),
            )
        effective_values = [item.effective_at for item in group if item.effective_at is not None]
        updated_values = [item.updated_at for item in group if item.updated_at is not None]
        events.append(
            CanonicalEvent(
                event_id=event_id,
                event_version=version,
                event_type=latest.event_type,
                entity_ids=latest.entity_ids,
                effective_key=latest.effective_key,
                key_facts=dict(latest.key_facts),
                direction=latest.direction,
                status=EventStatus.ACCEPTED,
                accepted=True,
                confirmed=_confirmed(group),
                sources=tuple(sources_by_ref.values()),
                source_published_at=min(item.published_at for item in group),
                ingested_at=max(item.ingested_at for item in group),
                effective_at=min(effective_values) if effective_values else None,
                updated_at=max(updated_values) if updated_values else None,
                material_update=any(item.material_update for item in group),
                numerical_claims=_merge_claims(group, valid_refs),
            )
        )
    events.sort(key=lambda event: (event.event_time, event.event_id), reverse=True)
    return events
