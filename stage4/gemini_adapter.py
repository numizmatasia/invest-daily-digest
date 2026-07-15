from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from stage4.models import CanonicalEvent, GroundedExplanation


def _render_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _deterministic_summary(event: CanonicalEvent, fact_refs: tuple[str, ...]) -> str:
    if not fact_refs:
        return f"Подтверждено событие {event.event_type} для {', '.join(event.entity_ids)}."
    if len(fact_refs) == 1:
        return _render_value(event.key_facts[fact_refs[0]])
    labels = {
        "fact": "Факт",
        "guidance": "Прогноз компании",
        "result": "Результат",
        "change": "Изменение",
        "reason": "Причина",
    }
    return "; ".join(
        f"{labels.get(ref, ref)}: {_render_value(event.key_facts[ref])}"
        for ref in fact_refs
    )


def _fallback(event: CanonicalEvent) -> GroundedExplanation:
    metadata_keys = {
        "identity",
        "display_title",
        "headline",
        "title",
        "candidate_ticker",
        "asset_ticker",
        "approved_portfolio_links",
    }
    fact_keys = tuple(sorted(str(key) for key in event.key_facts if key not in metadata_keys))
    if not fact_keys:
        fact_keys = ()
    return GroundedExplanation(
        event_id=event.event_id,
        event_version=event.event_version,
        summary=_deterministic_summary(event, fact_keys),
        source_refs=tuple(source.source_ref for source in event.sources),
        fact_refs=fact_keys,
        used_fallback=True,
    )


def validate_explanation(event: CanonicalEvent, payload: Any) -> GroundedExplanation:
    # Gemini may only select/order existing references. It cannot provide prose.
    allowed_keys = {"event_id", "event_version", "source_refs", "fact_refs"}
    if not isinstance(payload, dict) or set(payload) != allowed_keys:
        return _fallback(event)
    try:
        event_id = str(payload["event_id"])
        version = int(payload["event_version"])
        source_refs = tuple(str(value) for value in payload["source_refs"])
        fact_refs = tuple(str(value) for value in payload["fact_refs"])
    except (KeyError, TypeError, ValueError):
        return _fallback(event)
    valid_sources = {source.source_ref for source in event.sources}
    valid_fact_refs = {str(key) for key in event.key_facts}
    if (
        event_id != event.event_id
        or version != event.event_version
        or not source_refs
        or not fact_refs
        or not set(source_refs).issubset(valid_sources)
        or not set(fact_refs).issubset(valid_fact_refs)
    ):
        return _fallback(event)
    return GroundedExplanation(
        event_id=event_id,
        event_version=version,
        summary=_deterministic_summary(event, fact_refs),
        source_refs=source_refs,
        fact_refs=fact_refs,
        used_fallback=False,
    )


def explain_events(
    events: Iterable[CanonicalEvent],
    explainer: Callable[[CanonicalEvent], dict[str, Any]] | None,
) -> dict[str, GroundedExplanation]:
    result: dict[str, GroundedExplanation] = {}
    for event in events:
        if explainer is None:
            result[event.event_id] = _fallback(event)
            continue
        try:
            payload = explainer(event)
        except Exception:
            payload = None
        result[event.event_id] = validate_explanation(event, payload)
    return result
