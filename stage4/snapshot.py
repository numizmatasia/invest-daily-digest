from __future__ import annotations

from datetime import date
from typing import Iterable, Any

from infra.calendar_window import CalendarWindowService
from infra.config_snapshot import ConfigSnapshotService
from infra.snapshot_service import SnapshotService
from infra.types import sha256_json
from stage4.models import CanonicalEvent, SnapshotManifest


class Stage3SnapshotCoordinator:
    def __init__(self, repository) -> None:
        if repository is None:
            raise RuntimeError("STATE_STORE_REQUIRED")
        self.repository = repository
        self.calendar = CalendarWindowService(repository, timezone_name="Asia/Almaty")
        self.config = ConfigSnapshotService(repository)
        self.snapshots = SnapshotService(repository)

    def _stored_config_payload(self, config_snapshot_id: str) -> dict[str, Any]:
        # Current Stage 3 MemoryRepository exposes immutable snapshots through this map.
        # Production activation remains blocked until the selected persistent repository
        # provides an equivalent read method.
        records = getattr(self.repository, "config_snapshots", None)
        if not isinstance(records, dict):
            raise RuntimeError("STATE_STORE_CONFIG_SNAPSHOT_READ_REQUIRED")
        record = records.get(config_snapshot_id)
        if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
            raise RuntimeError("CONFIG_SNAPSHOT_NOT_FOUND")
        return dict(record["payload"])

    @staticmethod
    def _source_catalog_version(source_catalog: dict[str, Any]) -> str:
        return str(source_catalog.get("version") or ("source_catalog_sha256:" + sha256_json(source_catalog)))

    def _manifest(self, *, window, frozen: dict[str, Any]) -> SnapshotManifest:
        payload = self._stored_config_payload(str(frozen["config_snapshot_id"]))
        portfolio_raw = payload["portfolio"]
        watchlist_envelope = payload["watchlist"]
        watchlist_raw = watchlist_envelope.get("stage4_raw") if isinstance(watchlist_envelope, dict) else watchlist_envelope
        source_catalog = payload["source_catalog"]
        rules_version = str(payload["rules_version"] )
        return SnapshotManifest(
            snapshot_id=str(frozen["snapshot_id"]),
            window_start=window.window_start_at,
            event_cutoff_at=window.event_cutoff_at,
            snapshot_freeze_at=window.snapshot_freeze_at,
            portfolio_config_version="portfolio_sha256:" + sha256_json(portfolio_raw),
            watchlist_config_version="watchlist_sha256:" + sha256_json(watchlist_raw),
            rules_version=rules_version,
            source_catalog_version=self._source_catalog_version(source_catalog),
            event_refs=tuple(sorted(frozen["items"])),
            config_snapshot_id=str(frozen["config_snapshot_id"]),
            manifest_hash=str(frozen["manifest_hash"]),
        )

    def freeze(
        self,
        *,
        logical_date: date,
        portfolio_raw: dict[str, Any],
        watchlist_raw: Any,
        source_catalog: dict[str, Any],
        rules_version: str,
        events: Iterable[CanonicalEvent],
    ) -> SnapshotManifest:
        window = self.calendar.for_date(logical_date)
        snapshot_id = self.snapshots.snapshot_id(window)
        existing = self.repository.get_snapshot(snapshot_id)
        if existing and existing["state"] == "FROZEN":
            return self._manifest(window=window, frozen=existing)

        config = self.config.capture(
            portfolio=portfolio_raw,
            watchlist={"stage4_raw": watchlist_raw},
            user_limits={
                "portfolio_freshness_policy": None,
                "materiality_thresholds": None,
                "trade_thresholds": None,
            },
            source_catalog=source_catalog,
            rules_version=rules_version,
        )
        candidates = []
        for event in events:
            if event.event_time < window.window_start_at:
                continue
            candidates.append(
                {
                    "event_id": event.event_id,
                    "event_version": event.event_version,
                    "event_time": event.event_time,
                    "ingested_at": event.ingested_at,
                }
            )
        frozen = self.snapshots.build_and_freeze(
            window=window,
            config_snapshot_id=config["config_snapshot_id"],
            candidates=candidates,
        )
        return self._manifest(window=window, frozen=frozen)
