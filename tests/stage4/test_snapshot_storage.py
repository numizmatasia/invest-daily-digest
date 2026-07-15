from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from storage.repository import MemoryRepository
from stage4.delivery import StaleSnapshotError, prepare_shadow_delivery
from stage4.event_engine import build_events
from stage4.news_processor import process_news
from stage4.snapshot import Stage3SnapshotCoordinator
from tests.stage4_helpers import raw_item


def _event(repo, **kwargs):
    normalized, _ = process_news([raw_item(**kwargs)])
    return build_events(normalized, repo)[0]


def test_snapshot_manifest_has_all_master_fields(portfolio_raw, source_catalog):
    repo = MemoryRepository()
    event = _event(repo)
    manifest = Stage3SnapshotCoordinator(repo).freeze(
        logical_date=date(2026, 7, 15),
        portfolio_raw=portfolio_raw,
        watchlist_raw=["MU"],
        source_catalog=source_catalog,
        rules_version="stage4-rules-v2",
        events=[event],
    )
    assert manifest.snapshot_id == "portfolio_snapshot:Asia/Almaty:2026-07-15:06:25"
    assert manifest.window_start < manifest.event_cutoff_at < manifest.snapshot_freeze_at
    assert manifest.portfolio_config_version.startswith("portfolio_sha256:")
    assert manifest.watchlist_config_version.startswith("watchlist_sha256:")
    assert manifest.source_catalog_version == "sources-test-v1"
    assert manifest.event_refs == (f"{event.event_id}:{event.event_version}",)


def test_snapshot_create_if_absent_returns_same_frozen_manifest(portfolio_raw, source_catalog):
    repo = MemoryRepository()
    event = _event(repo)
    coordinator = Stage3SnapshotCoordinator(repo)
    first = coordinator.freeze(logical_date=date(2026,7,15), portfolio_raw=portfolio_raw, watchlist_raw=[], source_catalog=source_catalog, rules_version="r1", events=[event])
    second = coordinator.freeze(logical_date=date(2026,7,15), portfolio_raw=portfolio_raw, watchlist_raw=[], source_catalog=source_catalog, rules_version="r1", events=[])
    assert second.event_refs == first.event_refs
    assert second.manifest_hash == first.manifest_hash


def test_event_after_cutoff_is_not_in_frozen_snapshot(portfolio_raw, source_catalog):
    repo = MemoryRepository()
    event = _event(repo, published_at=datetime(2026,7,15,1,30,tzinfo=timezone.utc).isoformat(), ingested_at=datetime(2026,7,15,1,31,tzinfo=timezone.utc).isoformat())
    manifest = Stage3SnapshotCoordinator(repo).freeze(logical_date=date(2026,7,15), portfolio_raw=portfolio_raw, watchlist_raw=[], source_catalog=source_catalog, rules_version="r1", events=[event])
    assert manifest.event_refs == ()


def test_repository_version_change_after_freeze_blocks_delivery(portfolio_raw, source_catalog):
    repo = MemoryRepository()
    event = _event(repo)
    manifest = Stage3SnapshotCoordinator(repo).freeze(logical_date=date(2026,7,15), portfolio_raw=portfolio_raw, watchlist_raw=[], source_catalog=source_catalog, rules_version="r1", events=[event])
    _event(repo, key_facts={"identity":{"issuer":"MU","period":"2026-Q3"},"guidance":"revised"}, ingested_at=datetime(2026,7,15,1,2,tzinfo=timezone.utc).isoformat())
    with pytest.raises(StaleSnapshotError, match="DEFERRED_VERSION_CHANGED"):
        prepare_shadow_delivery(repository=repo, manifest=manifest, events=[event], text="x", now=datetime(2026,7,15,1,5,tzinfo=timezone.utc))


def test_no_stateless_bypass(portfolio_raw, source_catalog):
    with pytest.raises(RuntimeError, match="STATE_STORE_REQUIRED"):
        Stage3SnapshotCoordinator(None)


def test_event_before_window_start_is_not_in_snapshot(portfolio_raw, source_catalog):
    repo = MemoryRepository()
    event = _event(
        repo,
        published_at=datetime(2026,7,13,23,0,tzinfo=timezone.utc).isoformat(),
        ingested_at=datetime(2026,7,14,0,0,tzinfo=timezone.utc).isoformat(),
    )
    manifest = Stage3SnapshotCoordinator(repo).freeze(
        logical_date=date(2026,7,15), portfolio_raw=portfolio_raw, watchlist_raw=[],
        source_catalog=source_catalog, rules_version="r1", events=[event],
    )
    assert manifest.event_refs == ()


def test_effective_time_controls_calendar_inclusion(portfolio_raw, source_catalog):
    repo = MemoryRepository()
    event = _event(
        repo,
        published_at=datetime(2026,7,15,0,0,tzinfo=timezone.utc).isoformat(),
        effective_at=datetime(2026,7,13,23,0,tzinfo=timezone.utc).isoformat(),
    )
    manifest = Stage3SnapshotCoordinator(repo).freeze(
        logical_date=date(2026,7,15), portfolio_raw=portfolio_raw, watchlist_raw=[],
        source_catalog=source_catalog, rules_version="r1", events=[event],
    )
    assert manifest.event_refs == ()


def test_reused_frozen_snapshot_keeps_original_config_versions(portfolio_raw, source_catalog):
    repo = MemoryRepository()
    event = _event(repo)
    coordinator = Stage3SnapshotCoordinator(repo)
    first = coordinator.freeze(
        logical_date=date(2026,7,15), portfolio_raw=portfolio_raw, watchlist_raw={"watchlist":[]},
        source_catalog=source_catalog, rules_version="r1", events=[event],
    )
    changed_portfolio = {"Freedom":{"SPY":100.0},"Paidax":{"MU":100.0}}
    second = coordinator.freeze(
        logical_date=date(2026,7,15), portfolio_raw=changed_portfolio,
        watchlist_raw={"watchlist":[{"ticker":"AVGO"}]},
        source_catalog={"version":"changed","mandatory_sources":["other"]},
        rules_version="r2", events=[],
    )
    assert second.portfolio_config_version == first.portfolio_config_version
    assert second.watchlist_config_version == first.watchlist_config_version
    assert second.source_catalog_version == first.source_catalog_version
    assert second.rules_version == first.rules_version
    assert second.config_snapshot_id == first.config_snapshot_id


def test_missing_manifest_event_blocks_delivery(portfolio_raw, source_catalog):
    repo = MemoryRepository()
    event = _event(repo)
    manifest = Stage3SnapshotCoordinator(repo).freeze(
        logical_date=date(2026,7,15), portfolio_raw=portfolio_raw, watchlist_raw=[],
        source_catalog=source_catalog, rules_version="r1", events=[event],
    )
    with pytest.raises(StaleSnapshotError, match="SNAPSHOT_EVENT_MISSING"):
        prepare_shadow_delivery(repository=repo, manifest=manifest, events=[], text="x", now=datetime(2026,7,15,1,5,tzinfo=timezone.utc))
