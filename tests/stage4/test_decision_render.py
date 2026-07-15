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
    text = render_digest(decision, [event], explain_events([event], None))
    assert "Freedom:" in text and "Paidax:" in text
    assert "VT (DIRECT, 25.0%)" in text
    assert "VT (DIRECT, 50.0%)" in text
    assert "Торговая команда: отсутствует" in text


def test_no_invented_materiality_or_trade_thresholds(portfolio_raw):
    portfolio = load_current_portfolio(portfolio_raw)
    event = _event(entity_ids=["MU"])
    coverage = assess_coverage(mandatory_sources=["official"], source_results=[{"name":"official","ok":True}])
    decision = build_day_decision([event], portfolio, coverage)
    assert event.attention_state == "REVIEW_REQUIRED_NO_TRADE_COMMAND"
    assert decision.action == "NO_TRADE_COMMAND"
    assert "HIGH" not in render_digest(decision, [event], explain_events([event], None))


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
    assert explanation.summary == "change_pct=5"


def test_telegram_split_keeps_event_ids(portfolio_raw):
    portfolio = load_current_portfolio(portfolio_raw)
    events = [_event(source_ref=f"s{i}", url=f"https://e/{i}", effective_key=f"Q{i}", key_facts={"identity":{"issuer":"MU","period":f"Q{i}"},"detail":"x"*700}) for i in range(5)]
    coverage = assess_coverage(mandatory_sources=["official"], source_results=[{"name":"official","ok":True}])
    decision = build_day_decision(events, portfolio, coverage)
    text = render_digest(decision, events, explain_events(events, None))
    chunks = split_for_telegram(text, max_chars=700)
    joined = "\n".join(chunks)
    assert len(chunks) > 1
    assert all(event.event_id in joined for event in events)


def test_unverified_portfolio_freshness_blocks_personal_conclusion(portfolio_raw):
    portfolio = load_current_portfolio(portfolio_raw)
    event = _event(entity_ids=["MU"])
    coverage = assess_coverage(mandatory_sources=["official"], source_results=[{"name":"official","ok":True}])
    decision = build_day_decision([event], portfolio, coverage)
    assert decision.headline == "Инвестиционные выводы заблокированы"
    assert "PORTFOLIO_FRESHNESS_NOT_VERIFIED" in decision.warnings
    assert decision.action == "NO_TRADE_COMMAND"
