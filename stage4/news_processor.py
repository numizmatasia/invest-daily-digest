from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from stage4.models import NormalizedNews


_REJECT_CONTENT_KINDS = {"OPINION", "ROUTINE_NOTICE", "ADVERTISEMENT", "TECHNICAL_ANALYSIS"}
_ALLOWED_DIRECTIONS = {"POSITIVE", "NEGATIVE", "MIXED", "UNKNOWN"}


def _dt(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"{field} is required")
    if result.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return result.astimezone(timezone.utc)


def _optional_dt(value: Any, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    return _dt(value, field)


def normalize_item(raw: dict[str, Any]) -> NormalizedNews:
    if not isinstance(raw, dict):
        raise ValueError("raw item must be an object")
    event_type = str(raw.get("event_type", "")).strip().upper()
    event_evidence = raw.get("event_evidence")
    if not event_type or event_evidence is not True:
        raise ValueError("EVENT_NOT_PROVEN")
    identity = raw.get("key_facts", {}).get("identity") if isinstance(raw.get("key_facts"), dict) else None
    if not isinstance(identity, dict) or not identity:
        raise ValueError("STABLE_EVENT_IDENTITY_REQUIRED")
    source_ref = str(raw.get("source_ref", "")).strip()
    source_name = str(raw.get("source_name", "")).strip()
    independence_group = str(raw.get("independence_group", "")).strip()
    if not source_ref or not source_name or not independence_group:
        raise ValueError("SOURCE_EVIDENCE_REQUIRED")
    entities = tuple(sorted({str(value).strip().upper() for value in raw.get("entity_ids", []) if str(value).strip()}))
    if not entities:
        raise ValueError("ENTITY_IDS_REQUIRED")
    direction = str(raw.get("direction", "UNKNOWN")).strip().upper()
    if direction not in _ALLOWED_DIRECTIONS:
        direction = "UNKNOWN"
    claims = raw.get("numerical_claims", [])
    if not isinstance(claims, list):
        raise ValueError("numerical_claims must be a list")
    return NormalizedNews(
        source_ref=source_ref,
        source_name=source_name,
        source_class=str(raw.get("source_class", "OTHER")).strip().upper(),
        independence_group=independence_group,
        title=str(raw.get("title", "")).strip(),
        summary=str(raw.get("summary", "")).strip(),
        url=str(raw.get("url", "")).strip(),
        published_at=_dt(raw.get("published_at"), "published_at"),
        ingested_at=_dt(raw.get("ingested_at"), "ingested_at"),
        effective_at=_optional_dt(raw.get("effective_at"), "effective_at"),
        content_kind=str(raw.get("content_kind", "EVENT_REPORT")).strip().upper(),
        event_type=event_type,
        entity_ids=entities,
        effective_key=str(raw.get("effective_key", "")).strip(),
        key_facts=dict(raw.get("key_facts", {})),
        direction=direction,
        stable_event_id=(str(raw.get("stable_event_id")).strip() or None) if raw.get("stable_event_id") else None,
        numerical_claims=tuple(dict(item) for item in claims if isinstance(item, dict)),
    )


def process_news(raw_items: Iterable[dict[str, Any]]) -> tuple[list[NormalizedNews], list[dict[str, Any]]]:
    accepted: list[NormalizedNews] = []
    rejected: list[dict[str, Any]] = []
    technical_seen: set[tuple[str, str]] = set()
    for raw in raw_items:
        kind = str(raw.get("content_kind", "EVENT_REPORT")).strip().upper() if isinstance(raw, dict) else ""
        if kind in _REJECT_CONTENT_KINDS:
            rejected.append({"title": raw.get("title", ""), "reason": kind})
            continue
        try:
            item = normalize_item(raw)
        except (TypeError, ValueError) as exc:
            rejected.append({"title": raw.get("title", "") if isinstance(raw, dict) else "", "reason": str(exc)})
            continue
        key = (item.source_ref, item.url or item.title)
        if key in technical_seen:
            rejected.append({"title": item.title, "reason": "TECHNICAL_DUPLICATE"})
            continue
        technical_seen.add(key)
        accepted.append(item)
    return accepted, rejected
