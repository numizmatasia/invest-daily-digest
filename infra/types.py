from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json
from typing import Any


class JobType(StrEnum):
    PORTFOLIO_DAILY = "PORTFOLIO_DAILY"
    PORTFOLIO_INTRADAY = "PORTFOLIO_INTRADAY"
    HUNTING = "HUNTING"
    WATCHDOG = "WATCHDOG"
    SOURCE_INGESTION = "SOURCE_INGESTION"


class SnapshotState(StrEnum):
    PLANNED = "PLANNED"
    BUILDING = "BUILDING"
    FROZEN = "FROZEN"
    INVALIDATED = "INVALIDATED"
    ARCHIVED = "ARCHIVED"


class DeliveryState(StrEnum):
    PREPARED = "PREPARED"
    RESERVED = "RESERVED"
    SENDING = "SENDING"
    SENT = "SENT"
    DEFINITIVE_FAILED = "DEFINITIVE_FAILED"
    UNKNOWN_DELIVERY = "UNKNOWN_DELIVERY"
    PARTIAL_SENT = "PARTIAL_SENT"


class WatchdogAction(StrEnum):
    NO_ACTION = "NO_ACTION"
    DEGRADE_NOW = "DEGRADE_NOW"
    START_FAILOVER = "START_FAILOVER"
    RUNTIME_BLOCKED = "RUNTIME_BLOCKED"
    TECHNICAL_ALERT = "TECHNICAL_ALERT"


@dataclass(frozen=True)
class CalendarWindow:
    window_id: str
    logical_date: str
    timezone_name: str
    window_start_at: datetime
    event_cutoff_at: datetime
    snapshot_freeze_at: datetime


@dataclass(frozen=True)
class Lease:
    scope_key: str
    job_type: str
    logical_window: str
    owner_run_id: str
    fencing_token: int
    lease_until: datetime
    heartbeat_at: datetime


@dataclass
class RunHealth:
    run_id: str
    heartbeat_at: datetime | None
    last_progress_at: datetime | None
    active_request_deadline_at: datetime | None
    estimated_finish_at: datetime | None
    fencing_valid: bool
    process_failed: bool = False
    delivery_state: str | None = None


@dataclass
class WatchdogDecision:
    action: WatchdogAction
    reasons: list[str] = field(default_factory=list)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def sha256_json(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()
