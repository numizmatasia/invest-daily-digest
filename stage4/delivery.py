from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256

from infra.delivery_store import DeliveryStore
from infra.types import JobType
from stage4.models import CanonicalEvent, SnapshotManifest


class StaleSnapshotError(RuntimeError):
    pass


def validate_versions(manifest: SnapshotManifest, repository) -> None:
    if repository is None:
        raise RuntimeError("STATE_STORE_REQUIRED")
    changed: list[str] = []
    for ref in manifest.event_refs:
        event_id, version = ref.rsplit(":", 1)
        stored = repository.get_event(event_id)
        if not stored or int(stored.get("latest_version", 0)) != int(version):
            changed.append(ref)
    if changed:
        raise StaleSnapshotError("DEFERRED_VERSION_CHANGED:" + ",".join(changed))


def prepare_shadow_delivery(
    *,
    repository,
    manifest: SnapshotManifest,
    events: list[CanonicalEvent],
    text: str,
    now: datetime,
) -> dict:
    if repository is None:
        raise RuntimeError("STATE_STORE_REQUIRED")
    provided_refs = {f"{event.event_id}:{event.event_version}" for event in events}
    missing = sorted(set(manifest.event_refs) - provided_refs)
    if missing:
        raise StaleSnapshotError("SNAPSHOT_EVENT_MISSING:" + ",".join(missing))
    validate_versions(manifest, repository)
    scope_key = f"PORTFOLIO_DAILY:{manifest.snapshot_id}"
    run = repository.create_run(JobType.PORTFOLIO_DAILY.value, manifest.snapshot_id, "stage4-shadow")
    lease = repository.acquire_lease(
        scope_key=scope_key,
        job_type=JobType.PORTFOLIO_DAILY.value,
        logical_window=manifest.snapshot_id,
        owner_run_id=run["run_id"],
        now=now,
        ttl=timedelta(minutes=15),
    )
    if lease is None:
        raise RuntimeError("PORTFOLIO_DAILY_LEASE_UNAVAILABLE")
    digest_id = "dig_" + sha256((manifest.snapshot_id + "\n" + text).encode("utf-8")).hexdigest()[:24]
    delivery = DeliveryStore(repository).prepare(
        scope_key=scope_key,
        delivery_key=f"telegram:shadow:{manifest.snapshot_id}",
        digest_id=digest_id,
        run_id=run["run_id"],
        token=lease.fencing_token,
        text=text,
        now=now,
    )
    return {**delivery, "shadow_only": True, "telegram_send_called": False}
