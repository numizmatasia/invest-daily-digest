from datetime import timedelta

from infra.types import RunHealth, WatchdogAction
from infra.watchdog_service import WatchdogService


def _health(now, **overrides):
    values = dict(
        run_id="r1",
        heartbeat_at=now,
        last_progress_at=now,
        active_request_deadline_at=now + timedelta(minutes=2),
        estimated_finish_at=now + timedelta(minutes=3),
        fencing_valid=True,
        process_failed=False,
        delivery_state="PREPARED",
    )
    values.update(overrides)
    return RunHealth(**values)


def test_healthy_progress_does_not_failover(now):
    decision = WatchdogService().evaluate(health=_health(now), now=now, sla_deadline=now + timedelta(minutes=10), standby_fresh=True)
    assert decision.action == WatchdogAction.NO_ACTION


def test_slow_healthy_process_degrades_instead_of_failover(now):
    decision = WatchdogService().evaluate(health=_health(now, estimated_finish_at=now + timedelta(minutes=20)), now=now, sla_deadline=now + timedelta(minutes=10), standby_fresh=True)
    assert decision.action == WatchdogAction.DEGRADE_NOW


def test_stale_heartbeat_allows_failover(now):
    decision = WatchdogService().evaluate(health=_health(now, heartbeat_at=now - timedelta(minutes=6), active_request_deadline_at=None), now=now, sla_deadline=now + timedelta(minutes=10), standby_fresh=True)
    assert decision.action == WatchdogAction.START_FAILOVER


def test_stale_standby_blocks_failover(now):
    decision = WatchdogService().evaluate(health=_health(now, process_failed=True), now=now, sla_deadline=now + timedelta(minutes=10), standby_fresh=False)
    assert decision.action == WatchdogAction.RUNTIME_BLOCKED


def test_unknown_delivery_never_triggers_failover(now):
    decision = WatchdogService().evaluate(
        health=_health(now, delivery_state="UNKNOWN_DELIVERY", process_failed=True),
        now=now,
        sla_deadline=now + timedelta(minutes=10),
        standby_fresh=True,
    )
    assert decision.action == WatchdogAction.TECHNICAL_ALERT


def test_failed_sender_after_sending_does_not_resend(now):
    decision = WatchdogService().evaluate(
        health=_health(now, delivery_state="SENDING", process_failed=True),
        now=now,
        sla_deadline=now + timedelta(minutes=10),
        standby_fresh=True,
    )
    assert decision.action == WatchdogAction.TECHNICAL_ALERT
