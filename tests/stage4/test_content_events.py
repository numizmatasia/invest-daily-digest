from __future__ import annotations

from datetime import datetime, timezone

from storage.repository import MemoryRepository
from stage4.event_engine import build_events
from stage4.news_processor import process_news, process_news_windowed
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
        raw_item(source_ref="copy-1", source_name="Site A copy", source_class="TIER_2", independence_group="reuters", url="https://site-a.test/a"),
        raw_item(source_ref="copy-2", source_name="Site B copy", source_class="TIER_2", independence_group="reuters", url="https://site-b.test/a"),
    ])
    event = build_events(normalized, MemoryRepository())[0]
    assert event.confirmed is False


def _window():
    return (
        datetime(2026, 7, 14, 1, 25, tzinfo=timezone.utc),
        datetime(2026, 7, 15, 1, 25, tzinfo=timezone.utc),
    )


def test_old_micron_earnings_rejected_even_if_article_is_republished_today():
    window_start, cutoff = _window()
    accepted, calendar, rejected, stats = process_news_windowed(
        [
            raw_item(
                title="Micron reports strong earnings",
                event_type="EARNINGS",
                published_at=datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc).isoformat(),
                ingested_at=datetime(2026, 7, 15, 0, 1, tzinfo=timezone.utc).isoformat(),
                effective_at=datetime(2026, 6, 24, 20, 0, tzinfo=timezone.utc).isoformat(),
                key_facts={"identity": {"issuer": "MU", "period": "2026-Q3"}},
            )
        ],
        window_start_at=window_start,
        event_cutoff_at=cutoff,
    )
    assert accepted == []
    assert calendar == []
    assert rejected[0]["reason"] == "STALE_EVENT_BEFORE_WINDOW"
    assert stats["rejected_by_reason"]["STALE_EVENT_BEFORE_WINDOW"] == 1


def test_dated_event_without_effective_time_is_rejected():
    window_start, cutoff = _window()
    accepted, calendar, rejected, _ = process_news_windowed(
        [raw_item(event_type="EARNINGS", effective_at=None)],
        window_start_at=window_start,
        event_cutoff_at=cutoff,
    )
    assert accepted == []
    assert calendar == []
    assert rejected[0]["reason"] == "EFFECTIVE_AT_REQUIRED_FOR_DATED_EVENT"


def test_old_event_with_real_material_update_inside_window_is_allowed():
    window_start, cutoff = _window()
    accepted, calendar, rejected, _ = process_news_windowed(
        [
            raw_item(
                event_type="GUIDANCE",
                published_at=datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc).isoformat(),
                ingested_at=datetime(2026, 7, 15, 0, 1, tzinfo=timezone.utc).isoformat(),
                effective_at=datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc).isoformat(),
                updated_at=datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc).isoformat(),
                material_update=True,
            )
        ],
        window_start_at=window_start,
        event_cutoff_at=cutoff,
    )
    assert len(accepted) == 1
    assert calendar == []
    assert rejected == []


def test_future_cameco_results_move_to_calendar_not_news():
    window_start, cutoff = _window()
    accepted, calendar, rejected, _ = process_news_windowed(
        [
            raw_item(
                title="Cameco Q2 results scheduled",
                content_kind="UPCOMING_EARNINGS",
                event_type="EARNINGS",
                entity_ids=["CCJ"],
                effective_at=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc).isoformat(),
                key_facts={"identity": {"issuer": "CCJ", "period": "2026-Q2"}},
            )
        ],
        window_start_at=window_start,
        event_cutoff_at=cutoff,
    )
    assert accepted == []
    assert len(calendar) == 1
    assert rejected == []


def test_technical_price_signal_never_enters_day_events():
    window_start, cutoff = _window()
    accepted, calendar, rejected, _ = process_news_windowed(
        [raw_item(content_kind="TECHNICAL_ANALYSIS", title="IBIT bullish support signal")],
        window_start_at=window_start,
        event_cutoff_at=cutoff,
    )
    assert accepted == []
    assert calendar == []
    assert rejected[0]["reason"] == "TECHNICAL_ANALYSIS"


def test_single_reuters_source_is_confirmed_by_approved_source_rule():
    normalized, _ = process_news([
        raw_item(
            source_ref="reuters-1",
            source_name="Reuters",
            source_class="TIER_1",
            independence_group="Reuters",
        )
    ])
    event = build_events(normalized, MemoryRepository())[0]
    assert event.confirmed is True
