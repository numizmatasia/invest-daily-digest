from __future__ import annotations

from collections import Counter
from datetime import timezone
from typing import Iterable, Sequence

from stage4.models import (
    BrokerPortfolio,
    CanonicalEvent,
    DayDecision,
    GroundedExplanation,
    NormalizedNews,
    PortfolioSnapshot,
)


_BROKERS = ("Freedom", "Paidax")
_SINGLE_SOURCE_CONFIRMERS = {"REUTERS", "BLOOMBERG", "AP", "ASSOCIATED PRESS", "FINANCIAL TIMES", "FT", "WALL STREET JOURNAL", "WSJ"}

_REASON_RU = {
    "OPINION": "мнение",
    "ROUTINE_NOTICE": "обычное уведомление",
    "ADVERTISEMENT": "реклама",
    "TECHNICAL_ANALYSIS": "технический прогноз",
    "PRICE_PREDICTION": "прогноз цены",
    "CLICKBAIT": "кликбейт",
    "EVENT_NOT_PROVEN": "событие не доказано",
    "STABLE_EVENT_IDENTITY_REQUIRED": "нет устойчивой идентификации события",
    "SOURCE_EVIDENCE_REQUIRED": "нет данных об источнике",
    "TECHNICAL_DUPLICATE": "технический дубль",
    "PUBLISHED_AFTER_CUTOFF_DEFERRED": "опубликовано после cutoff — перенесено",
    "UPDATED_AFTER_CUTOFF_DEFERRED": "обновлено после cutoff — перенесено",
    "EFFECTIVE_AT_REQUIRED_FOR_DATED_EVENT": "нет даты фактического события",
    "STALE_EVENT_BEFORE_WINDOW": "старое событие",
    "STALE_PUBLICATION_BEFORE_WINDOW": "старая публикация",
    "UPDATED_BEFORE_PUBLISHED": "ошибка дат",
    "PUBLISHED_AFTER_INGESTED": "ошибка метаданных времени",
}


def _event_title(event: CanonicalEvent) -> str:
    for key in ("display_title", "headline", "title"):
        value = event.key_facts.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    entities = ", ".join(event.entity_ids)
    return f"{event.event_type}: {entities}"


def _source_quality(event: CanonicalEvent) -> str:
    classes = {source.source_class for source in event.sources}
    if classes & {"OFFICIAL", "REGULATOR", "EXCHANGE"}:
        return "высокая — официальный источник"
    if any(
        source.source_name.strip().upper() in _SINGLE_SOURCE_CONFIRMERS
        for source in event.sources
    ):
        return "высокая — один утверждённый первоклассный источник"
    independent = {source.independence_group for source in event.sources}
    if event.confirmed and len(independent) >= 2:
        return f"высокая — {len(independent)} независимых источника"
    return "не подтверждено"


def _event_fact(event: CanonicalEvent, explanation: GroundedExplanation) -> str:
    text = explanation.summary.strip()
    if len(text) > 420:
        text = text[:417].rstrip() + "…"
    return text


def _confirmed(events: Sequence[CanonicalEvent]) -> list[CanonicalEvent]:
    return [event for event in events if event.accepted and event.confirmed]


def _unverified(events: Sequence[CanonicalEvent]) -> list[CanonicalEvent]:
    return [event for event in events if event.accepted and not event.confirmed]


def _portfolio_event_rows(
    broker: str,
    events: Sequence[CanonicalEvent],
) -> list[tuple[float, CanonicalEvent, list[dict]]]:
    rows: list[tuple[float, CanonicalEvent, list[dict]]] = []
    for event in _confirmed(events):
        relations = list(event.broker_relations.get(broker, []))
        if not relations:
            continue
        relations.sort(key=lambda item: (-float(item["declared_weight_pct"]), item["ticker"]))
        rows.append((max(float(item["declared_weight_pct"]) for item in relations), event, relations))
    rows.sort(key=lambda item: (-item[0], item[1].event_time, item[1].event_id))
    return rows


def _held_tickers(portfolio: PortfolioSnapshot) -> set[str]:
    result: set[str] = set()
    for broker in _BROKERS:
        result.update(position.ticker for position in portfolio.brokers[broker].positions)
    return result


def _candidate_ticker(event: CanonicalEvent) -> str | None:
    for key in ("candidate_ticker", "asset_ticker"):
        value = event.key_facts.get(key)
        ticker = str(value or "").strip().upper()
        if ticker:
            return ticker
    return None


def _calendar_line(item: NormalizedNews) -> str:
    moment = item.effective_at or item.published_at
    date_text = moment.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return f"• {date_text}: {item.title or item.event_type}"


def _exclusion_lines(rejected: Sequence[dict]) -> list[str]:
    counts = Counter(str(item.get("reason", "UNKNOWN")) for item in rejected)
    if not counts:
        return ["• Исключённых материалов нет."]
    lines: list[str] = []
    for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        label = _REASON_RU.get(reason, reason)
        lines.append(f"• {label}: {count}")
    return lines


def render_digest(
    decision: DayDecision,
    events: Iterable[CanonicalEvent],
    explanations: dict[str, GroundedExplanation],
    *,
    portfolio: PortfolioSnapshot | None = None,
    watchlist: Iterable[str] = (),
    calendar_items: Sequence[NormalizedNews] = (),
    rejected: Sequence[dict] = (),
    processing_stats: dict | None = None,
) -> str:
    accepted = [event for event in events if event.accepted]
    confirmed = _confirmed(accepted)
    unverified = _unverified(accepted)
    watch = {str(ticker).strip().upper() for ticker in watchlist if str(ticker).strip()}

    lines = [
        "📊 УТРЕННИЙ ИНВЕСТИЦИОННЫЙ ДАЙДЖЕСТ — SHADOW",
        "",
        "📋 Что делать сегодня",
        f"• {decision.headline}.",
        f"• {decision.rationale}",
        "• Непроверенные материалы не влияют на общий вывод.",
        "",
        "🔄 Что действительно изменилось",
    ]

    if confirmed:
        for event in confirmed[:6]:
            explanation = explanations[event.event_id]
            lines.append(f"• {_event_title(event)}")
            lines.append(f"  {_event_fact(event, explanation)}")
            lines.append(f"  Надёжность: {_source_quality(event)}.")
    else:
        lines.append("• Подтверждённых актуальных событий в окне отчёта нет.")

    if portfolio is not None:
        lines.extend(["", "📊 Влияние на мои инвестиции"])
        for broker in _BROKERS:
            lines.append(f"• {broker}")
            rows = _portfolio_event_rows(broker, accepted)
            if not rows:
                lines.append("  Подтверждённых связанных событий нет.")
                continue
            for _, event, relations in rows[:5]:
                relation_text = ", ".join(
                    f"{item['ticker']} — {float(item['declared_weight_pct']):.2f}%"
                    for item in relations
                )
                lines.append(f"  {_event_title(event)}")
                lines.append(f"  Затронуты: {relation_text}.")
                lines.append("  Действие: сохранить позиции; не покупать и не продавать только по этой новости.")

    if watch:
        watch_events = [
            event for event in confirmed
            if set(event.entity_ids) & watch and not any(event.broker_relations.get(broker) for broker in _BROKERS)
        ]
        lines.extend(["", "👁 Watch List"])
        if watch_events:
            for event in watch_events[:4]:
                tickers = ", ".join(sorted(set(event.entity_ids) & watch))
                lines.append(f"• {tickers}: {_event_title(event)} — наблюдать, не догонять цену без отдельной оценки.")
        else:
            lines.append("• Подтверждённых новых событий по Watch List нет.")

    if portfolio is not None:
        held = _held_tickers(portfolio)
        candidates: list[tuple[str, CanonicalEvent]] = []
        for event in confirmed:
            ticker = _candidate_ticker(event)
            if not ticker or ticker in held or ticker in watch:
                continue
            if any(event.broker_relations.get(broker) for broker in _BROKERS):
                continue
            candidates.append((ticker, event))
        lines.extend(["", "🔎 Новые возможности вне портфеля"])
        if candidates:
            for ticker, event in candidates[:3]:
                lines.append(f"• {ticker}: {_event_title(event)}")
                lines.append("  Статус: кандидат на углублённый анализ, не команда на покупку.")
        else:
            lines.append("• Подтверждённых новых кандидатов с явно указанным тикером нет.")

    lines.extend(["", "📅 Календарь"])
    if calendar_items:
        lines.extend(_calendar_line(item) for item in calendar_items[:5])
    else:
        lines.append("• Новых календарных событий не выявлено.")

    if unverified:
        lines.extend(["", "⚠️ Требуют дополнительной проверки"])
        for event in unverified[:4]:
            lines.append(f"• {_event_title(event)} — не влияет на итог дня.")

    lines.extend(["", "🗑 Что исключено"])
    lines.extend(_exclusion_lines(rejected))

    stats = processing_stats or {}
    lines.extend(["", "🧭 Полнота данных"])
    lines.append(
        "• Входных материалов: {raw}; актуальных публикаций: {accepted}; "
        "календарь: {calendar}; исключено: {rejected}; подтверждённых событий: {confirmed}.".format(
            raw=stats.get("raw_count", len(accepted) + len(rejected) + len(calendar_items)),
            accepted=stats.get("accepted_publications", len(accepted)),
            calendar=stats.get("calendar_publications", len(calendar_items)),
            rejected=stats.get("rejected_publications", len(rejected)),
            confirmed=len(confirmed),
        )
    )
    lines.append(f"• Покрытие обязательных источников: {decision.coverage_status.value}.")

    if decision.warnings:
        visible = [
            warning for warning in decision.warnings
            if warning not in {
                "PORTFOLIO_COMPOSITION_DECLARED_CURRENT_UNTIL_USER_REPORTS_CHANGE",
                "WEIGHTS_ARE_LAST_DECLARED_NOT_LIVE_MARKET_WEIGHTS",
            }
        ]
        if visible:
            lines.extend(["", "Технические ограничения:"])
            lines.extend(f"• {warning}" for warning in visible[:6])

    lines.extend([
        "",
        "⚠️ Состав портфеля считается действующим до сообщения пользователя об изменении.",
        "Текущие рыночные веса и котировки пока не пересчитываются автоматически.",
    ])
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
            cut = paragraph.rfind("\n", 0, max_chars)
            if cut < max_chars // 2:
                cut = max_chars
            chunks.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip("\n")
        current = paragraph
    if current:
        chunks.append(current)
    return chunks
