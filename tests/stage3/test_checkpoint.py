from datetime import timedelta

import pytest

from infra.checkpoint_store import CheckpointStore
from infra.lease_service import LeaseService
from storage.repository import LostFenceError


def _lease(repo, now, owner="one", ttl=300):
    run = repo.create_run("PORTFOLIO_DAILY", "2026-07-13", owner)
    lease = LeaseService(repo).acquire(job_type="PORTFOLIO_DAILY", logical_window="2026-07-13", run_id=run["run_id"], now=now, ttl_seconds=ttl)
    return run, lease


def test_checkpoint_is_saved_atomically(repo, now):
    run, lease = _lease(repo, now)
    record = CheckpointStore(repo).save_completed(scope_key=lease.scope_key, run_id=run["run_id"], token=lease.fencing_token, checkpoint_key="event:e1", payload={"status": "ok"}, now=now)
    assert record["state"] == "COMPLETED"
    assert len(record["payload_hash"]) == 64


def test_reserve_skips_completed_work(repo, now):
    run, lease = _lease(repo, now)
    store = CheckpointStore(repo)
    store.save_completed(scope_key=lease.scope_key, run_id=run["run_id"], token=lease.fencing_token, checkpoint_key="e1", payload={"x": 1}, now=now)
    assert store.pending(lease.scope_key, ["e1", "e2"]) == ["e2"]


def test_late_old_owner_checkpoint_is_rejected(repo, now):
    run1, lease1 = _lease(repo, now, ttl=1)
    run2 = repo.create_run("PORTFOLIO_DAILY", "2026-07-13", "two")
    LeaseService(repo).acquire(job_type="PORTFOLIO_DAILY", logical_window="2026-07-13", run_id=run2["run_id"], now=now + timedelta(seconds=2))
    with pytest.raises(LostFenceError):
        CheckpointStore(repo).save_completed(scope_key=lease1.scope_key, run_id=run1["run_id"], token=lease1.fencing_token, checkpoint_key="e1", payload={"x": 1}, now=now + timedelta(seconds=2))
