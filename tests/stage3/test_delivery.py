import pytest

from infra.delivery_store import DeliveryStore
from infra.lease_service import LeaseService
from storage.repository import IdempotencyConflictError, InvalidTransitionError


def _prepared(repo, now):
    run = repo.create_run("PORTFOLIO_DAILY", "2026-07-13", "owner")
    lease = LeaseService(repo).acquire(job_type="PORTFOLIO_DAILY", logical_window="2026-07-13", run_id=run["run_id"], now=now)
    store = DeliveryStore(repo)
    record = store.prepare(scope_key=lease.scope_key, delivery_key="portfolio:2026-07-13", digest_id="d-1", run_id=run["run_id"], token=lease.fencing_token, text="digest", now=now)
    return run, lease, store, record


def test_success_path_saves_message_id(repo, now):
    run, lease, store, _ = _prepared(repo, now)
    store.reserve("portfolio:2026-07-13", run["run_id"], lease.fencing_token, now)
    store.start_sending("portfolio:2026-07-13", run["run_id"], lease.fencing_token, now)
    sent = store.mark_sent("portfolio:2026-07-13", run["run_id"], lease.fencing_token, 123, now)
    assert sent["state"] == "SENT"
    assert sent["message_id"] == 123


def test_timeout_creates_unknown_delivery(repo, now):
    run, lease, store, _ = _prepared(repo, now)
    store.reserve("portfolio:2026-07-13", run["run_id"], lease.fencing_token, now)
    store.start_sending("portfolio:2026-07-13", run["run_id"], lease.fencing_token, now)
    unknown = store.mark_unknown("portfolio:2026-07-13", run["run_id"], lease.fencing_token, "timeout after request", now)
    assert unknown["state"] == "UNKNOWN_DELIVERY"


def test_unknown_delivery_forbids_resend(repo, now):
    run, lease, store, _ = _prepared(repo, now)
    store.reserve("portfolio:2026-07-13", run["run_id"], lease.fencing_token, now)
    store.start_sending("portfolio:2026-07-13", run["run_id"], lease.fencing_token, now)
    store.mark_unknown("portfolio:2026-07-13", run["run_id"], lease.fencing_token, "timeout", now)
    with pytest.raises(InvalidTransitionError):
        store.reserve("portfolio:2026-07-13", run["run_id"], lease.fencing_token, now)


def test_delivery_key_is_idempotent(repo, now):
    run, lease, store, first = _prepared(repo, now)
    second = store.prepare(
        scope_key=lease.scope_key,
        delivery_key="portfolio:2026-07-13",
        digest_id=first["digest_id"],
        run_id=run["run_id"],
        token=lease.fencing_token,
        text="digest",
        now=now,
    )
    assert second["digest_id"] == first["digest_id"]
    assert len(repo.deliveries) == 1


def test_same_delivery_key_with_different_content_is_rejected(repo, now):
    run, lease, store, _ = _prepared(repo, now)
    with pytest.raises(IdempotencyConflictError):
        store.prepare(
            scope_key=lease.scope_key,
            delivery_key="portfolio:2026-07-13",
            digest_id="different",
            run_id=run["run_id"],
            token=lease.fencing_token,
            text="different content",
            now=now,
        )
