from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from infra.types import CalendarWindow
from storage.repository import MemoryRepository


class SnapshotService:
    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    @staticmethod
    def snapshot_id(window: CalendarWindow) -> str:
        return f"portfolio_snapshot:{window.timezone_name}:{window.logical_date}:06:25"

    def build_and_freeze(
        self,
        *,
        window: CalendarWindow,
        config_snapshot_id: str,
        candidates: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        snapshot_id = self.snapshot_id(window)
        existing = self.repository.get_snapshot(snapshot_id)
        if existing and existing["state"] == "FROZEN":
            return existing
        self.repository.create_snapshot(snapshot_id, window.window_id, config_snapshot_id)
        for item in candidates:
            event_time = item.get("event_time")
            ingested_at = item["ingested_at"]
            if event_time is not None and event_time > window.event_cutoff_at:
                continue
            if ingested_at > window.snapshot_freeze_at:
                continue
            self.repository.add_snapshot_item(snapshot_id, item)
        return self.repository.freeze_snapshot(snapshot_id, window.snapshot_freeze_at)
