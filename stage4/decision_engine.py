from __future__ import annotations

from typing import Iterable

from stage4.models import CanonicalEvent, CoverageAssessment, DayDecision, PortfolioSnapshot, RelationType


_BROKERS = ("Freedom", "Paidax")


def _explicit_thematic_targets(event: CanonicalEvent) -> set[str]:
    targets = event.key_facts.get("approved_portfolio_links", [])
    if not isinstance(targets, list):
        return set()
    return {str(value).strip().upper() for value in targets if str(value).strip()}


def route_relations(event: CanonicalEvent, portfolio: PortfolioSnapshot) -> dict[str, list[dict]]:
    relations: dict[str, list[dict]] = {broker: [] for broker in _BROKERS}
    entities = set(event.entity_ids)
    thematic_targets = _explicit_thematic_targets(event)
    for broker in _BROKERS:
        broker_portfolio = portfolio.brokers[broker]
        for position in broker_portfolio.positions:
            relation_type: RelationType | None = None
            evidence = ""
            if position.ticker in entities:
                relation_type = RelationType.DIRECT
                evidence = "canonical entity_id matches held ticker"
            elif position.ticker in thematic_targets:
                relation_type = RelationType.THEMATIC
                evidence = "explicit approved_portfolio_links field"
            if relation_type is not None:
                relations[broker].append(
                    {
                        "ticker": position.ticker,
                        "relation_type": relation_type.value,
                        "declared_weight_pct": position.declared_weight_pct,
                        "evidence": evidence,
                    }
                )
        relations[broker].sort(key=lambda item: (-float(item["declared_weight_pct"]), item["ticker"]))
    event.broker_relations = relations
    return relations


def assess_event(event: CanonicalEvent, portfolio: PortfolioSnapshot) -> str:
    relations = route_relations(event, portfolio)
    has_portfolio_relation = any(relations[broker] for broker in _BROKERS)
    if not event.confirmed:
        state = "UNVERIFIED_EXCLUDED_FROM_DAY_DECISION"
    elif has_portfolio_relation:
        state = "CONFIRMED_PORTFOLIO_REVIEW_NO_TRADE_COMMAND"
    else:
        state = "CONFIRMED_FACT_NO_CURRENT_PORTFOLIO_LINK"
    event.attention_state = state
    return state


def build_day_decision(
    events: Iterable[CanonicalEvent],
    portfolio: PortfolioSnapshot,
    coverage: CoverageAssessment,
) -> DayDecision:
    accepted = [event for event in events if event.accepted]
    for event in accepted:
        assess_event(event, portfolio)

    warnings = list(coverage.warnings) + list(portfolio.warnings)
    if coverage.runtime_status == "RUNTIME_BLOCKED":
        return DayDecision(
            action="NO_TRADE_COMMAND",
            headline="Персональный вывод ограничен неполным покрытием источников",
            rationale=(
                "Подтверждённые факты показываются, но неполный обязательный набор источников "
                "не позволяет считать обзор окончательным."
            ),
            coverage_status=coverage.status,
            accepted_event_ids=tuple(event.event_id for event in accepted),
            warnings=tuple(warnings + ["SOURCE_COVERAGE_NOT_READY"]),
        )

    confirmed_related = [
        event
        for event in accepted
        if event.confirmed and any(event.broker_relations.get(broker) for broker in _BROKERS)
    ]
    confirmed_unrelated = [
        event
        for event in accepted
        if event.confirmed and not any(event.broker_relations.get(broker) for broker in _BROKERS)
    ]

    if confirmed_related:
        headline = "Срочных торговых действий нет; есть подтверждённые события для контроля"
        rationale = (
            "Приоритет определяется подтверждённостью события и размером затронутых позиций. "
            "Текущих котировок и правил входа пока нет, поэтому покупка или продажа не назначается."
        )
    elif confirmed_unrelated:
        headline = "По текущему портфелю срочных действий нет"
        rationale = (
            "Подтверждённые события вне портфеля рассматриваются только как кандидаты "
            "на отдельное исследование."
        )
    elif accepted:
        headline = "Подтверждённых оснований для действия нет"
        rationale = "Непроверенные материалы исключены из общего решения дня."
    else:
        headline = "Подтверждённых актуальных событий нет"
        rationale = "Старые, календарные и непроверенные материалы не используются как события дня."

    return DayDecision(
        action="NO_TRADE_COMMAND",
        headline=headline,
        rationale=rationale,
        coverage_status=coverage.status,
        accepted_event_ids=tuple(event.event_id for event in accepted),
        warnings=tuple(warnings),
    )
