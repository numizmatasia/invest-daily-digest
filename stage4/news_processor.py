from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from stage4.models import NormalizedNews


_REJECT_CONTENT_KINDS = {
    "OPINION",
    "ROUTINE_NOTICE",
    "ADVERTISEMENT",
    "TECHNICAL_ANALYSIS",
    "PRICE_PREDICTION",
    "CLICKBAIT",
}
_CALENDAR_CONTENT_KINDS = {
    "CALENDAR",
    "UPCOMING_EVENT",
    "UPCOMING_EARNINGS",
    "EVENT_PREVIEW",
}
_ALLOWED_DIRECTIONS = {"POSITIVE", "NEGATIVE", "MIXED", "UNKNOWN"}
_EFFECTIVE_AT_REQUIRED = {
    "EARNINGS",
    "FINANCIAL_RESULTS",
    "GUIDANCE",
    "DIVIDEND",
    "IPO",
    "LISTING",
    "STOCK_SPLIT",
    "MERGER",
    "ACQUISITION",
    "SANCTIONS",
    "REGULATORY_DECISION",
    "FED_DECISION",
    "RATE_DECISION",
    "CPI_RELEASE",
    "EMPLOYMENT_REPORT",
    "CONTRACT_AWARD",
}


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
    published_at = _dt(raw.get("published_at"), "published_at")
    ingested_at = _dt(raw.get("ingested_at"), "ingested_at")
    updated_at = _optional_dt(raw.get("updated_at"), "updated_at")
    if updated_at is not None and updated_at < published_at:
        raise ValueError("UPDATED_BEFORE_PUBLISHED")
    if published_at > ingested_at + timedelta(minutes=15):
        raise ValueError("PUBLISHED_AFTER_INGESTED")
    return NormalizedNews(
        source_ref=source_ref,
        source_name=source_name,
        source_class=str(raw.get("source_class", "OTHER")).strip().upper(),
        independence_group=independence_group,
        title=str(raw.get("title", "")).strip(),
        summary=str(raw.get("summary", "")).strip(),
        url=str(raw.get("url", "")).strip(),
        published_at=published_at,
        ingested_at=ingested_at,
        effective_at=_optional_dt(raw.get("effective_at"), "effective_at"),
        updated_at=updated_at,
        material_update=raw.get("material_update") is True,
        content_kind=str(raw.get("content_kind", "EVENT_REPORT")).strip().upper(),
        event_type=event_type,
        entity_ids=entities,
        effective_key=str(raw.get("effective_key", "")).strip(),
        key_facts=dict(raw.get("key_facts", {})),
        direction=direction,
        stable_event_id=(str(raw.get("stable_event_id")).strip() or None) if raw.get("stable_event_id") else None,
        numerical_claims=tuple(dict(item) for item in claims if isinstance(item, dict)),
    )


def _base_process(raw_items: Iterable[dict[str, Any]]) -> tuple[list[NormalizedNews], list[dict[str, Any]]]:
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


def process_news(raw_items: Iterable[dict[str, Any]]) -> tuple[list[NormalizedNews], list[dict[str, Any]]]:
    """Compatibility path for isolated unit tests.

    The live shadow pipeline must call process_news_windowed so date-sensitive
    freshness rules are always applied.
    """
    return _base_process(raw_items)


def process_news_windowed(
    raw_items: Iterable[dict[str, Any]],
    *,
    window_start_at: datetime,
    event_cutoff_at: datetime,
) -> tuple[list[NormalizedNews], list[NormalizedNews], list[dict[str, Any]], dict[str, Any]]:
    window_start = _dt(window_start_at, "window_start_at")
    cutoff = _dt(event_cutoff_at, "event_cutoff_at")
    if not window_start < cutoff:
        raise ValueError("INVALID_REPORT_WINDOW")

    raw_list = list(raw_items)
    normalized, rejected = _base_process(raw_list)
    accepted: list[NormalizedNews] = []
    calendar: list[NormalizedNews] = []

    for item in normalized:
        if item.content_kind in _CALENDAR_CONTENT_KINDS:
            calendar.append(item)
            continue

        if item.published_at > cutoff:
            rejected.append({"title": item.title, "reason": "PUBLISHED_AFTER_CUTOFF_DEFERRED"})
            continue
        if item.updated_at is not None and item.updated_at > cutoff:
            rejected.append({"title": item.title, "reason": "UPDATED_AFTER_CUTOFF_DEFERRED"})
            continue

        if item.effective_at is not None and item.effective_at > cutoff:
            calendar.append(item)
            continue

        if item.event_type in _EFFECTIVE_AT_REQUIRED and item.effective_at is None:
            rejected.append({"title": item.title, "reason": "EFFECTIVE_AT_REQUIRED_FOR_DATED_EVENT"})
            continue

        event_time = item.effective_at or item.published_at
        valid_material_update = bool(
            item.material_update
            and item.updated_at is not None
            and window_start <= item.updated_at <= cutoff
        )

        if event_time < window_start and not valid_material_update:
            rejected.append({"title": item.title, "reason": "STALE_EVENT_BEFORE_WINDOW"})
            continue
        if item.published_at < window_start and not valid_material_update:
            rejected.append({"title": item.title, "reason": "STALE_PUBLICATION_BEFORE_WINDOW"})
            continue

        accepted.append(item)

    reason_counts = Counter(str(item.get("reason", "UNKNOWN")) for item in rejected)
    stats = {
        "raw_count": len(raw_list),
        "accepted_publications": len(accepted),
        "calendar_publications": len(calendar),
        "rejected_publications": len(rejected),
        "rejected_by_reason": dict(sorted(reason_counts.items())),
        "window_start_at": window_start.isoformat(),
        "event_cutoff_at": cutoff.isoformat(),
    }
    return accepted, calendar, rejected, stats
