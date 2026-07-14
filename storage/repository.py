from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
from hashlib import sha256
from threading import RLock
from typing import Any
from uuid import uuid4

from infra.types import CalendarWindow, DeliveryState, Lease, canonical_json, sha256_json


class DuplicateRecordError(RuntimeError):
    pass


class FrozenSnapshotError(RuntimeError):
    pass


class InvalidTransitionError(RuntimeError):
    pass


class LostFenceError(RuntimeError):
    pass


class IdempotencyConflictError(RuntimeError):
    pass


class MemoryRepository:
    """Deterministic Stage 3 test repository.

    It is intentionally not a production database. PostgreSQL remains the
    production-class store; this repository makes state-machine tests fast and
    reproducible before a provider is selected.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self.raw_items: dict[str, dict[str, Any]] = {}
        self.raw_unique: dict[tuple[str, str], str] = {}
        self.events: dict[str, dict[str, Any]] = {}
        self.config_snapshots: dict[str, dict[str, Any]] = {}
        self.windows: dict[str, CalendarWindow] = {}
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.leases: dict[str, Lease] = {}
        self.fence_counters: dict[str, int] = {}
        self.checkpoints: dict[tuple[str, str], dict[str, Any]] = {}
        self.deliveries: dict[str, dict[str, Any]] = {}
        self.alerts: dict[str, dict[str, Any]] = {}

    # Raw journal -----------------------------------------------------
    def append_raw(self, item: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        with self._lock:
            upstream_id = item.get("upstream_id")
            if upstream_id:
                unique_key = (item["source_id"], str(upstream_id))
            else:
                unique_key = (item["source_id"], item["content_hash"])
            existing_id = self.raw_unique.get(unique_key)
            if existing_id:
                return deepcopy(self.raw_items[existing_id]), False
            raw_item_id = item.get("raw_item_id") or str(uuid4())
            record = deepcopy(item)
            record["raw_item_id"] = raw_item_id
            self.raw_items[raw_item_id] = record
            self.raw_unique[unique_key] = raw_item_id
            return deepcopy(record), True

    def mutate_raw(self, raw_item_id: str, updates: dict[str, Any]) -> None:
        raise PermissionError("raw journal is append-only")

    # Event store -----------------------------------------------------
    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self.events.get(event_id)
            return deepcopy(value) if value else None

    def create_event(
        self,
        *,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
        canonical_hash: str,
        source_ref: str,
        now: datetime,
    ) -> dict[str, Any]:
        with self._lock:
            if event_id in self.events:
                raise DuplicateRecordError(event_id)
            record = {
                "event_id": event_id,
                "event_type": event_type,
                "latest_version": 1,
                "versions": {
                    1: {
                        "event_version": 1,
                        "payload": deepcopy(payload),
                        "canonical_hash": canonical_hash,
                        "sources": {source_ref},
                        "created_at": now,
                    }
                },
            }
            self.events[event_id] = record
            return deepcopy(record)

    def add_event_version(
        self,
        *,
        event_id: str,
        payload: dict[str, Any],
        canonical_hash: str,
        source_ref: str,
        now: datetime,
    ) -> tuple[int, bool]:
        with self._lock:
            event = self.events[event_id]
            latest = event["versions"][event["latest_version"]]
            if latest["canonical_hash"] == canonical_hash:
                latest["sources"].add(source_ref)
                return event["latest_version"], False
            new_version = event["latest_version"] + 1
            event["versions"][new_version] = {
                "event_version": new_version,
                "payload": deepcopy(payload),
                "canonical_hash": canonical_hash,
                "sources": {source_ref},
                "created_at": now,
            }
            event["latest_version"] = new_version
            return new_version, True

    def mutate_event_version(self, event_id: str, version: int, updates: dict[str, Any]) -> None:
        raise PermissionError("event versions are immutable")

    # Config snapshot -------------------------------------------------
    def create_config_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            config_hash = sha256_json(payload)
            existing = self.config_snapshots.get(config_hash)
            if existing:
                return deepcopy(existing)
            record = {
                "config_snapshot_id": config_hash,
                "payload": deepcopy(payload),
                "config_hash": config_hash,
                "immutable": True,
            }
            self.config_snapshots[config_hash] = record
            return deepcopy(record)

    # Calendar and snapshot ------------------------------------------
    def put_window(self, window: CalendarWindow) -> CalendarWindow:
        with self._lock:
            existing = self.windows.get(window.window_id)
            if existing and existing != window:
                raise DuplicateRecordError("calendar window conflict")
            self.windows[window.window_id] = window
            return window

    def create_snapshot(self, snapshot_id: str, window_id: str, config_snapshot_id: str) -> dict[str, Any]:
        with self._lock:
            existing = self.snapshots.get(snapshot_id)
            if existing:
                if (
                    existing["window_id"] != window_id
                    or existing["config_snapshot_id"] != config_snapshot_id
                ):
                    raise DuplicateRecordError("snapshot identity conflict")
                return deepcopy(existing)
            record = {
                "snapshot_id": snapshot_id,
                "window_id": window_id,
                "config_snapshot_id": config_snapshot_id,
                "state": "BUILDING",
                "items": {},
                "manifest_hash": None,
                "frozen_at": None,
            }
            self.snapshots[snapshot_id] = record
            return deepcopy(record)

    def add_snapshot_item(self, snapshot_id: str, item: dict[str, Any]) -> None:
        with self._lock:
            snapshot = self.snapshots[snapshot_id]
            if snapshot["state"] == "FROZEN":
                raise FrozenSnapshotError(snapshot_id)
            key = f"{item['event_id']}:{item['event_version']}"
            snapshot["items"][key] = deepcopy(item)

    def freeze_snapshot(self, snapshot_id: str, frozen_at: datetime) -> dict[str, Any]:
        with self._lock:
            snapshot = self.snapshots[snapshot_id]
            if snapshot["state"] == "FROZEN":
                return deepcopy(snapshot)
            manifest = [snapshot["items"][key] for key in sorted(snapshot["items"])]
            snapshot["manifest_hash"] = sha256_json(manifest)
            snapshot["state"] = "FROZEN"
            snapshot["frozen_at"] = frozen_at
            return deepcopy(snapshot)

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self.snapshots.get(snapshot_id)
            return deepcopy(value) if value else None

    # Runs and leases -------------------------------------------------
    def create_run(self, job_type: str, logical_window: str, owner_id: str) -> dict[str, Any]:
        with self._lock:
            run_id = str(uuid4())
            record = {
                "run_id": run_id,
                "job_type": job_type,
                "logical_window": logical_window,
                "owner_id": owner_id,
                "state": "CREATED",
                "heartbeat_at": None,
                "last_progress_at": None,
                "fencing_token": None,
            }
            self.runs[run_id] = record
            return deepcopy(record)

    def acquire_lease(
        self,
        *,
        scope_key: str,
        job_type: str,
        logical_window: str,
        owner_run_id: str,
        now: datetime,
        ttl: timedelta,
    ) -> Lease | None:
        with self._lock:
            current = self.leases.get(scope_key)
            if current and current.lease_until > now:
                if current.owner_run_id == owner_run_id:
                    return current
                return None
            token = self.fence_counters.get(scope_key, 0) + 1
            self.fence_counters[scope_key] = token
            lease = Lease(
                scope_key=scope_key,
                job_type=job_type,
                logical_window=logical_window,
                owner_run_id=owner_run_id,
                fencing_token=token,
                lease_until=now + ttl,
                heartbeat_at=now,
            )
            self.leases[scope_key] = lease
            self.runs[owner_run_id]["fencing_token"] = token
            self.runs[owner_run_id]["heartbeat_at"] = now
            return lease

    def verify_fence(self, scope_key: str, owner_run_id: str, token: int, now: datetime) -> bool:
        with self._lock:
            lease = self.leases.get(scope_key)
            return bool(
                lease
                and lease.owner_run_id == owner_run_id
                and lease.fencing_token == token
                and lease.lease_until > now
            )

    def renew_lease(
        self,
        *,
        scope_key: str,
        owner_run_id: str,
        token: int,
        now: datetime,
        ttl: timedelta,
    ) -> Lease:
        with self._lock:
            if not self.verify_fence(scope_key, owner_run_id, token, now):
                raise LostFenceError(scope_key)
            current = self.leases[scope_key]
            renewed = Lease(
                scope_key=current.scope_key,
                job_type=current.job_type,
                logical_window=current.logical_window,
                owner_run_id=current.owner_run_id,
                fencing_token=current.fencing_token,
                lease_until=now + ttl,
                heartbeat_at=now,
            )
            self.leases[scope_key] = renewed
            self.runs[owner_run_id]["heartbeat_at"] = now
            return renewed

    # Checkpoints -----------------------------------------------------
    def save_checkpoint(
        self,
        *,
        scope_key: str,
        run_id: str,
        token: int,
        now: datetime,
        checkpoint_key: str,
        state: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            if not self.verify_fence(scope_key, run_id, token, now):
                raise LostFenceError(scope_key)
            record = {
                "run_id": run_id,
                "checkpoint_key": checkpoint_key,
                "state": state,
                "payload": deepcopy(payload),
                "payload_hash": sha256_json(payload),
                "fencing_token": token,
            }
            self.checkpoints[(scope_key, checkpoint_key)] = record
            self.runs[run_id]["last_progress_at"] = now
            return deepcopy(record)

    def completed_checkpoint_keys(self, scope_key: str) -> set[str]:
        with self._lock:
            return {
                key
                for (scope, key), value in self.checkpoints.items()
                if scope == scope_key and value["state"] == "COMPLETED"
            }

    # Delivery --------------------------------------------------------
    def create_delivery(
        self,
        *,
        scope_key: str,
        delivery_key: str,
        digest_id: str,
        run_id: str,
        token: int,
        content_hash: str,
        now: datetime,
    ) -> dict[str, Any]:
        with self._lock:
            if delivery_key in self.deliveries:
                existing = self.deliveries[delivery_key]
                if (
                    existing["digest_id"] != digest_id
                    or existing["content_hash"] != content_hash
                ):
                    raise IdempotencyConflictError(delivery_key)
                return deepcopy(existing)
            if not self.verify_fence(scope_key, run_id, token, now):
                raise LostFenceError(scope_key)
            record = {
                "scope_key": scope_key,
                "delivery_key": delivery_key,
                "digest_id": digest_id,
                "run_id": run_id,
                "fencing_token": token,
                "content_hash": content_hash,
                "state": DeliveryState.PREPARED.value,
                "message_id": None,
                "unknown_reason": None,
            }
            self.deliveries[delivery_key] = record
            return deepcopy(record)

    def transition_delivery(
        self,
        *,
        delivery_key: str,
        expected: set[str],
        new_state: str,
        run_id: str,
        token: int,
        now: datetime,
        message_id: int | None = None,
        unknown_reason: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            record = self.deliveries[delivery_key]
            if record["state"] not in expected:
                raise InvalidTransitionError(f"{record['state']} -> {new_state}")
            if not self.verify_fence(record["scope_key"], run_id, token, now):
                raise LostFenceError(record["scope_key"])
            if record["state"] in {
                DeliveryState.SENT.value,
                DeliveryState.UNKNOWN_DELIVERY.value,
                DeliveryState.PARTIAL_SENT.value,
            }:
                raise InvalidTransitionError("terminal delivery state")
            if new_state == DeliveryState.SENT.value and message_id is None:
                raise ValueError("message_id is required for SENT")
            if new_state == DeliveryState.UNKNOWN_DELIVERY.value and not unknown_reason:
                raise ValueError("unknown_reason is required")
            record["state"] = new_state
            if message_id is not None:
                record["message_id"] = message_id
            if unknown_reason is not None:
                record["unknown_reason"] = unknown_reason
            return deepcopy(record)

    # Alerts ----------------------------------------------------------
    def create_alert(self, dedup_key: str, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        with self._lock:
            existing = self.alerts.get(dedup_key)
            if existing:
                return deepcopy(existing), False
            record = deepcopy(payload)
            record["alert_id"] = str(uuid4())
            record["dedup_key"] = dedup_key
            self.alerts[dedup_key] = record
            return deepcopy(record), True
