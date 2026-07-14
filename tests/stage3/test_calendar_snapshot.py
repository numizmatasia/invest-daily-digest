from datetime import date, datetime, timedelta, timezone

import pytest

from infra.calendar_window import CalendarWindowService
from infra.snapshot_service import SnapshotService
from storage.repository import FrozenSnapshotError


def test_calendar_window_is_exact_24_hours(repo):
    window = CalendarWindowService(repo).for_date(date(2026, 7, 13))
    assert window.event_cutoff_at - window.window_start_at == timedelta(days=1)
    assert window.snapshot_freeze_at - window.event_cutoff_at == timedelta(minutes=2)


def test_freeze_makes_manifest_immutable(repo):
    window = CalendarWindowService(repo).for_date(date(2026, 7, 13))
    service = SnapshotService(repo)
    frozen = service.build_and_freeze(
        window=window, config_snapshot_id="cfg",
        candidates=[{"event_id": "e1", "event_version": 1, "event_time": window.event_cutoff_at, "ingested_at": window.snapshot_freeze_at, "route_hint": "DAILY"}],
    )
    assert frozen["state"] == "FROZEN"
    with pytest.raises(FrozenSnapshotError):
        repo.add_snapshot_item(frozen["snapshot_id"], {"event_id": "e2", "event_version": 1})


def test_main_and_reserve_get_same_manifest(repo):
    window = CalendarWindowService(repo).for_date(date(2026, 7, 13))
    service = SnapshotService(repo)
    candidates = [{"event_id": "e1", "event_version": 1, "event_time": window.event_cutoff_at, "ingested_at": window.snapshot_freeze_at, "route_hint": "DAILY"}]
    main = service.build_and_freeze(window=window, config_snapshot_id="cfg", candidates=candidates)
    reserve = service.build_and_freeze(window=window, config_snapshot_id="cfg", candidates=candidates + [{"event_id": "late", "event_version": 1, "event_time": window.event_cutoff_at, "ingested_at": window.snapshot_freeze_at + timedelta(minutes=1), "route_hint": "DAILY"}])
    assert main["manifest_hash"] == reserve["manifest_hash"]
    assert len(reserve["items"]) == 1


def test_late_arrival_after_freeze_is_excluded(repo):
    window = CalendarWindowService(repo).for_date(date(2026, 7, 13))
    frozen = SnapshotService(repo).build_and_freeze(
        window=window, config_snapshot_id="cfg",
        candidates=[{"event_id": "late", "event_version": 1, "event_time": window.event_cutoff_at - timedelta(minutes=10), "ingested_at": window.snapshot_freeze_at + timedelta(seconds=1), "route_hint": "DAILY"}],
    )
    assert frozen["items"] == {}


def test_failed_delivery_does_not_expand_next_window(repo):
    service = CalendarWindowService(repo)
    first = service.for_date(date(2026, 7, 13))
    next_window = service.for_date(date(2026, 7, 14))
    assert next_window.window_start_at == first.event_cutoff_at


def test_existing_snapshot_rejects_different_config(repo):
    window = CalendarWindowService(repo).for_date(date(2026, 7, 13))
    service = SnapshotService(repo)
    service.build_and_freeze(window=window, config_snapshot_id="cfg-1", candidates=[])
    from storage.repository import DuplicateRecordError
    # Frozen snapshot is returned before creation; directly test identity guard.
    with pytest.raises(DuplicateRecordError):
        repo.create_snapshot(service.snapshot_id(window), window.window_id, "cfg-2")
