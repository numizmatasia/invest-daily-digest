from __future__ import annotations

from storage.repository import MemoryRepository
from stage4.event_engine import build_events
from stage4.news_processor import process_news
from tests.stage4_helpers import raw_item


def test_routine_notice_removed_without_title_keyword_inference():
    accepted, rejected = process_news([raw_item(content_kind="ROUTINE_NOTICE")])
    assert accepted == []
    assert rejected[0]["reason"] == "ROUTINE_NOTICE"


def test_opinion_is_not_earnings_event():
    accepted, rejected = process_news([raw_item(content_kind="OPINION", event_type="EARNINGS")])
    assert accepted == []
    assert rejected[0]["reason"] == "OPINION"


def test_keyword_without_explicit_event_evidence_is_rejected():
    accepted, rejected = process_news([raw_item(title="IPO earnings sanctions merger", event_evidence=False)])
    assert accepted == []
    assert rejected[0]["reason"] == "EVENT_NOT_PROVEN"


def test_four_skhynix_ipo_sources_merge_one_physical_event():
    items = [
        raw_item(
            source_ref=f"src-{i}",
            source_name=f"Source {i}",
            independence_group=f"group-{i}",
            source_class="TIER_1",
            url=f"https://example.test/{i}",
            event_type="IPO",
            entity_ids=["SKHY"],
            effective_key="2026-07-10",
            key_facts={"identity": {"issuer": "SK Hynix", "listing_date": "2026-07-10"}},
        )
        for i in range(4)
    ]
    normalized, _ = process_news(items)
    events = build_events(normalized, MemoryRepository())
    assert len(events) == 1
    assert len(events[0].sources) == 4
    assert events[0].confirmed is True


def test_ipo_and_memory_supply_are_separate_events():
    normalized, _ = process_news([
        raw_item(event_type="IPO", entity_ids=["SKHY"], effective_key="2026-07-10", key_facts={"identity": {"issuer":"SK Hynix","listing_date":"2026-07-10"}}),
        raw_item(source_ref="src-2", url="https://example.test/2", event_type="MEMORY_SUPPLY", entity_ids=["SKHY"], effective_key="2026-H2", key_facts={"identity": {"issuer":"SK Hynix","period":"2026-H2"}}),
    ])
    events = build_events(normalized, MemoryRepository())
    assert {event.event_type for event in events} == {"IPO", "MEMORY_SUPPLY"}


def test_syndicated_copies_do_not_count_as_independent():
    normalized, _ = process_news([
        raw_item(source_ref="reuters-1", source_name="Reuters", source_class="TIER_2", independence_group="reuters", url="https://reuters.test/a"),
        raw_item(source_ref="yahoo-1", source_name="Yahoo copy", source_class="TIER_2", independence_group="reuters", url="https://yahoo.test/a"),
    ])
    event = build_events(normalized, MemoryRepository())[0]
    assert event.confirmed is False
