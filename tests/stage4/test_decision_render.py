from __future__ import annotations

from storage.repository import MemoryRepository
from stage4.completeness import assess_coverage
from stage4.decision_engine import build_day_decision
from stage4.event_engine import build_events
from stage4.gemini_adapter import explain_events
from stage4.news_processor import process_news
from stage4.portfolio_loader import load_current_portfolio
from stage4.renderer import render_digest, split_for_telegram
from tests.stage4_helpers import raw_item


def _event(**kwargs):
    normalized, _ = process_news([raw_item(**kwargs)])
    return build_events(normalized, MemoryRepository())[0]


def test_missing_mandatory_source_set_never_returns_full():
    coverage = assess_coverage(mandatory_sources=[], source_results=[])
    assert coverage.status.value == "INSUFFICIENT"
    assert coverage.runtime_status == "RUNTIME_BLOCKED"


def test_freedom_and_paidax_render_separately(portfolio_raw):
    portfolio = load_current_portfolio(portfolio_raw)
    event = _event(entity_ids=["VT"])
    coverage = assess_coverage(mandatory_sources=["official"], source_results=[{"name":"official","ok":True}])
    decision = build_day_decision([event], portfolio, coverage)
    text = render_digest(decision, [event], explain_events([event], None), portfolio=portfolio)
    assert "• Freedom" in text and "• Paidax" in text
    assert "VT — 25.00%" in text
    assert "VT — 50.00%" in text
    assert "не покупать и не продавать только по этой новости" in text


def test_no_invented_materiality_or_trade_thresholds(portfolio_raw):
    portfolio = load_current_portfolio(portfolio_raw)
    event = _event(entity_ids=["MU"])
    coverage = assess_coverage(mandatory_sources=["official"], source_results=[{"name":"official","ok":True}])
    decision = build_day_decision([event], portfolio, coverage)
    assert event.attention_state == "CONFIRMED_PORTFOLIO_REVIEW_NO_TRADE_COMMAND"
    assert decision.action == "NO_TRADE_COMMAND"
    assert "HIGH" not in render_digest(decision, [event], explain_events([event], None), portfolio=portfolio)


def test_thematic_relation_requires_explicit_approved_link(portfolio_raw):
    portfolio = load_current_portfolio(portfolio_raw)
    event = _event(entity_ids=["IRAN"], event_type="SANCTIONS", key_facts={"identity":{"country":"IRAN","date":"2026-07-15"}, "approved_portfolio_links":["XLE"]})
    coverage = assess_coverage(mandatory_sources=["official"], source_results=[{"name":"official","ok":True}])
    build_day_decision([event], portfolio, coverage)
    assert event.broker_relations["Freedom"][0]["ticker"] == "XLE"


def test_free_text_from_gemini_is_rejected_and_cannot_add_number():
    event = _event()
    explanation = explain_events([event], lambda e: {"event_id":e.event_id,"event_version":e.event_version,"summary":"Рост 999%","source_refs":[e.sources[0].source_ref],"fact_refs":["identity"]})[event.event_id]
    assert explanation.used_fallback is True
    assert "999" not in explanation.summary


def test_grounded_gemini_may_only_select_existing_refs():
    event = _event(key_facts={"identity":{"issuer":"MU","period":"2026-Q3"},"change_pct":5}, numerical_claims=[{"label":"Change","value":5,"unit":"%","source_ref":"src-1"}])
    explanation = explain_events([event], lambda e: {"event_id":e.event_id,"event_version":e.event_version,"source_refs":["src-1"],"fact_refs":["change_pct"]})[event.event_id]
    assert explanation.used_fallback is False
    assert explanation.summary == "5"


def test_telegram_split_preserves_all_rendered_event_titles(portfolio_raw):
    portfolio = load_current_portfolio(portfolio_raw)
    events = [
        _event(
            source_ref=f"s{i}",
            url=f"https://e/{i}",
            effective_key=f"Q{i}",
            key_facts={
                "identity":{"issuer":"MU","period":f"Q{i}"},
                "display_title": f"Событие номер {i}",
                "detail":"x"*700,
            },
        )
        for i in range(5)
    ]
    coverage = assess_coverage(mandatory_sources=["official"], source_results=[{"name":"official","ok":True}])
    decision = build_day_decision(events, portfolio, coverage)
    text = render_digest(decision, events, explain_events(events, None), portfolio=portfolio)
    chunks = split_for_telegram(text, max_chars=700)
    joined = "\n".join(chunks)
    assert len(chunks) > 1
    assert all(f"Событие номер {i}" in joined for i in range(5))


def test_declared_portfolio_remains_usable_until_user_reports_change(portfolio_raw):
    portfolio = load_current_portfolio(portfolio_raw)
    event = _event(entity_ids=["MU"])
    coverage = assess_coverage(mandatory_sources=["official"], source_results=[{"name":"official","ok":True}])
    decision = build_day_decision([event], portfolio, coverage)
    assert portfolio.freshness_status == "DECLARED_CURRENT"
    assert decision.headline.startswith("Срочных торговых действий нет")
    assert decision.action == "NO_TRADE_COMMAND"


def test_report_has_approved_structure_and_new_candidate(portfolio_raw):
    portfolio = load_current_portfolio(portfolio_raw)
    event = _event(
        entity_ids=["ASML"],
        event_type="EARNINGS",
        key_facts={
            "identity": {"issuer": "ASML", "period": "2026-Q2"},
            "display_title": "ASML повысила прогноз",
            "candidate_ticker": "ASML",
        },
    )
    coverage = assess_coverage(mandatory_sources=["official"], source_results=[{"name":"official","ok":True}])
    decision = build_day_decision([event], portfolio, coverage)
    text = render_digest(
        decision,
        [event],
        explain_events([event], None),
        portfolio=portfolio,
        watchlist=("AVGO", "SKHY"),
        rejected=[
            {"title": "Old MU", "reason": "STALE_EVENT_BEFORE_WINDOW"},
            {"title": "IBIT signal", "reason": "TECHNICAL_ANALYSIS"},
        ],
        processing_stats={
            "raw_count": 3,
            "accepted_publications": 1,
            "calendar_publications": 0,
            "rejected_publications": 2,
        },
    )
    assert "📋 Что делать сегодня" in text
    assert "🔄 Что действительно изменилось" in text
    assert "📊 Влияние на мои инвестиции" in text
    assert "🔎 Новые возможности вне портфеля" in text
    assert "ASML: ASML повысила прогноз" in text
    assert "старое событие: 1" in text
    assert "технический прогноз: 1" in text
    assert "Входных материалов: 3" in text
