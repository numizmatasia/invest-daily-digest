from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from stage4.completeness import assess_coverage
from stage4.decision_engine import build_day_decision
from stage4.delivery import prepare_shadow_delivery
from stage4.event_engine import build_events
from stage4.gemini_adapter import explain_events
from stage4.models import CanonicalEvent
from stage4.news_processor import process_news
from stage4.portfolio_loader import load_current_portfolio, load_watchlist
from stage4.renderer import render_digest, split_for_telegram
from stage4.snapshot import Stage3SnapshotCoordinator


def run_shadow_morning(
    *,
    repository,
    logical_date: date,
    now: datetime,
    raw_items: list[dict[str, Any]],
    portfolio_raw: dict[str, Any],
    watchlist_raw: Any,
    source_catalog: dict[str, Any],
    source_results: list[dict[str, Any]],
    rules_version: str,
    explainer: Callable[[CanonicalEvent], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if repository is None:
        raise RuntimeError("STATE_STORE_REQUIRED")
    portfolio = load_current_portfolio(portfolio_raw)
    watchlist, watchlist_warnings, _ = load_watchlist(watchlist_raw)
    normalized, rejected = process_news(raw_items)
    events = build_events(normalized, repository)
    manifest = Stage3SnapshotCoordinator(repository).freeze(
        logical_date=logical_date,
        portfolio_raw=portfolio_raw,
        watchlist_raw=watchlist_raw,
        source_catalog=source_catalog,
        rules_version=rules_version,
        events=events,
    )
    included_refs = set(manifest.event_refs)
    included = [event for event in events if f"{event.event_id}:{event.event_version}" in included_refs]
    coverage = assess_coverage(
        mandatory_sources=source_catalog.get("mandatory_sources", []),
        source_results=source_results,
    )
    decision = build_day_decision(included, portfolio, coverage)
    if watchlist_warnings:
        decision = decision.__class__(
            action=decision.action,
            headline=decision.headline,
            rationale=decision.rationale,
            coverage_status=decision.coverage_status,
            accepted_event_ids=decision.accepted_event_ids,
            warnings=decision.warnings + watchlist_warnings,
        )
    explanations = explain_events(included, explainer)
    text = render_digest(decision, included, explanations)
    chunks = split_for_telegram(text)
    delivery = prepare_shadow_delivery(
        repository=repository,
        manifest=manifest,
        events=events,
        text=text,
        now=now,
    )
    return {
        "portfolio": portfolio,
        "watchlist": watchlist,
        "normalized": normalized,
        "rejected": rejected,
        "all_events": events,
        "events": included,
        "coverage": coverage,
        "decision": decision,
        "manifest": manifest,
        "text": text,
        "chunks": chunks,
        "delivery": delivery,
    }
