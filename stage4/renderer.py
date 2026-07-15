from __future__ import annotations

from typing import Iterable

from stage4.models import CanonicalEvent, DayDecision, GroundedExplanation


_BROKERS = ("Freedom", "Paidax")


def _claims(event: CanonicalEvent) -> list[str]:
    valid_refs = {source.source_ref for source in event.sources}
    result: list[str] = []
    for claim in event.numerical_claims:
        source_ref = str(claim.get("source_ref", ""))
        if source_ref not in valid_refs:
            continue
        label = str(claim.get("label", "")).strip()
        value = claim.get("value")
        unit = str(claim.get("unit", "")).strip()
        result.append(f"{label}: {value}{(' ' + unit) if unit else ''} [{source_ref}]")
    return result


def _event_lines(index: int, event: CanonicalEvent, explanation: GroundedExplanation) -> list[str]:
    source_refs = ", ".join(source.source_ref for source in event.sources)
    lines = [
        f"Событие {index}: {event.event_type}",
        f"ID: {event.event_id}:v{event.event_version}",
        f"Статус: {event.attention_state}",
        f"Факты: {explanation.summary}",
        f"Источники: {source_refs}",
    ]
    claims = _claims(event)
    if claims:
        lines.append("Числа:")
        lines.extend(f"- {claim}" for claim in claims)
    return lines


def render_digest(
    decision: DayDecision,
    events: Iterable[CanonicalEvent],
    explanations: dict[str, GroundedExplanation],
) -> str:
    accepted = [event for event in events if event.accepted]
    lines = [
        "УТРЕННИЙ ПОРТФЕЛЬНЫЙ ДАЙДЖЕСТ — SHADOW",
        f"Покрытие: {decision.coverage_status.value}",
        f"Итог дня: {decision.headline}",
        f"Основание: {decision.rationale}",
        "Торговая команда: отсутствует",
    ]
    if decision.warnings:
        lines.extend(["", "Ограничения:"])
        lines.extend(f"- {warning}" for warning in decision.warnings)

    for broker in _BROKERS:
        related = [event for event in accepted if event.broker_relations.get(broker)]
        lines.extend(["", broker + ":"])
        if not related:
            lines.append("- Подтвержденных связанных событий нет.")
            continue
        for event in related:
            relation_text = ", ".join(
                f"{item['ticker']} ({item['relation_type']}, {item['declared_weight_pct']}%)"
                for item in event.broker_relations[broker]
            )
            lines.append(f"- Событие {accepted.index(event) + 1}: {relation_text}")

    lines.extend(["", f"Принятые события: {len(accepted)}"])
    for index, event in enumerate(accepted, start=1):
        lines.append("")
        lines.extend(_event_lines(index, event, explanations[event.event_id]))
    return "\n".join(lines)


def split_for_telegram(text: str, *, max_chars: int = 3500) -> list[str]:
    if max_chars < 200:
        raise ValueError("max_chars is too small")
    if len(text) <= max_chars:
        return [text]
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else current + "\n\n" + paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > max_chars:
            chunks.append(paragraph[:max_chars])
            paragraph = paragraph[max_chars:]
        current = paragraph
    if current:
        chunks.append(current)
    return chunks
