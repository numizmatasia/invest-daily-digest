from datetime import timedelta

import pytest

from infra.lease_service import LeaseService
from storage.repository import LostFenceError


def test_only_one_owner_acquires_active_lease(repo, now):
    service = LeaseService(repo)
    r1 = repo.create_run("PORTFOLIO_DAILY", "2026-07-13", "one")
    r2 = repo.create_run("PORTFOLIO_DAILY", "2026-07-13", "two")
    first = service.acquire(job_type="PORTFOLIO_DAILY", logical_window="2026-07-13", run_id=r1["run_id"], now=now)
    second = service.acquire(job_type="PORTFOLIO_DAILY", logical_window="2026-07-13", run_id=r2["run_id"], now=now)
    assert first is not None
    assert second is None


def test_expired_lease_can_be_taken_over(repo, now):
    service = LeaseService(repo)
    r1 = repo.create_run("PORTFOLIO_DAILY", "2026-07-13", "one")
    r2 = repo.create_run("PORTFOLIO_DAILY", "2026-07-13", "two")
    first = service.acquire(job_type="PORTFOLIO_DAILY", logical_window="2026-07-13", run_id=r1["run_id"], now=now, ttl_seconds=1)
    second = service.acquire(job_type="PORTFOLIO_DAILY", logical_window="2026-07-13", run_id=r2["run_id"], now=now + timedelta(seconds=2))
    assert second is not None
    assert second.fencing_token > first.fencing_token


def test_old_owner_is_rejected_after_takeover(repo, now):
    service = LeaseService(repo)
    r1 = repo.create_run("PORTFOLIO_DAILY", "2026-07-13", "one")
    r2 = repo.create_run("PORTFOLIO_DAILY", "2026-07-13", "two")
    first = service.acquire(job_type="PORTFOLIO_DAILY", logical_window="2026-07-13", run_id=r1["run_id"], now=now, ttl_seconds=1)
    service.acquire(job_type="PORTFOLIO_DAILY", logical_window="2026-07-13", run_id=r2["run_id"], now=now + timedelta(seconds=2))
    with pytest.raises(LostFenceError):
        service.assert_current(scope_key=first.scope_key, run_id=r1["run_id"], token=first.fencing_token, now=now + timedelta(seconds=2))


def test_daily_does_not_block_intraday(repo, now):
    service = LeaseService(repo)
    daily_run = repo.create_run("PORTFOLIO_DAILY", "2026-07-13", "daily")
    intra_run = repo.create_run("PORTFOLIO_INTRADAY", "e1:1", "intra")
    daily = service.acquire(job_type="PORTFOLIO_DAILY", logical_window="2026-07-13", run_id=daily_run["run_id"], now=now)
    intra = service.acquire(job_type="PORTFOLIO_INTRADAY", logical_window="e1:1", run_id=intra_run["run_id"], now=now)
    assert daily is not None and intra is not None
    assert daily.scope_key != intra.scope_key


def test_hunting_has_separate_scope(repo, now):
    service = LeaseService(repo)
    run = repo.create_run("HUNTING", "regular", "hunt")
    lease = service.acquire(job_type="HUNTING", logical_window="regular", run_id=run["run_id"], now=now)
    assert lease.scope_key == "HUNTING:regular"


def test_same_owner_reacquire_keeps_same_fencing_token(repo, now):
    service = LeaseService(repo)
    run = repo.create_run("PORTFOLIO_DAILY", "2026-07-13", "one")
    first = service.acquire(
        job_type="PORTFOLIO_DAILY", logical_window="2026-07-13",
        run_id=run["run_id"], now=now,
    )
    second = service.acquire(
        job_type="PORTFOLIO_DAILY", logical_window="2026-07-13",
        run_id=run["run_id"], now=now,
    )
    assert second.fencing_token == first.fencing_token
