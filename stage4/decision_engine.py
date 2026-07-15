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
    event.broker_relations = relations
    return relations


def assess_event(event: CanonicalEvent, portfolio: PortfolioSnapshot) -> str:
    relations = route_relations(event, portfolio)
    has_portfolio_relation = any(relations[broker] for broker in _BROKERS)
    if not event.confirmed:
        state = "UNVERIFIED_FACT_ONLY"
    elif has_portfolio_relation:
        state = "REVIEW_REQUIRED_NO_TRADE_COMMAND"
    else:
        state = "FACT_ONLY_NO_PROVEN_PORTFOLIO_LINK"
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
    blocking_reasons: list[str] = []
    if coverage.runtime_status == "RUNTIME_BLOCKED":
        blocking_reasons.append("SOURCE_COVERAGE_NOT_READY")
    if portfolio.freshness_status != "VERIFIED":
        blocking_reasons.append("PORTFOLIO_FRESHNESS_NOT_VERIFIED")
    if blocking_reasons:
        return DayDecision(
            action="NO_TRADE_COMMAND",
            headline="Инвестиционные выводы заблокированы",
            rationale="Не подтверждены обязательные условия для персонального инвестиционного вывода.",
            coverage_status=coverage.status,
            accepted_event_ids=tuple(event.event_id for event in accepted),
            warnings=tuple(warnings + blocking_reasons + ["INVESTMENT_CONCLUSIONS_BLOCKED"]),
        )
    confirmed_related = [
        event for event in accepted
        if event.confirmed and any(event.broker_relations.get(broker) for broker in _BROKERS)
    ]
    if confirmed_related:
        headline = f"Требуют проверки: {len(confirmed_related)} подтвержденных события"
        rationale = "Связь доказана, но пороги существенности и торговые действия не угадываются."
    elif accepted:
        headline = "Подтвержденных оснований для действия нет"
        rationale = "События перечислены как факты; доказанной портфельной связи недостаточно."
    else:
        headline = "Вывод ограничен покрытием" if coverage.status.value != "FULL" else "Подтвержденных событий нет"
        rationale = "Итог сформирован без торговой команды."
    return DayDecision(
        action="NO_TRADE_COMMAND",
        headline=headline,
        rationale=rationale,
        coverage_status=coverage.status,
        accepted_event_ids=tuple(event.event_id for event in accepted),
        warnings=tuple(warnings),
    )
