from __future__ import annotations

from datetime import datetime, timedelta

from infra.types import RunHealth, WatchdogAction, WatchdogDecision


class WatchdogService:
    def __init__(
        self,
        *,
        heartbeat_timeout: timedelta = timedelta(minutes=5),
        progress_timeout: timedelta = timedelta(minutes=5),
    ) -> None:
        self.heartbeat_timeout = heartbeat_timeout
        self.progress_timeout = progress_timeout

    def evaluate(
        self,
        *,
        health: RunHealth,
        now: datetime,
        sla_deadline: datetime,
        standby_fresh: bool,
    ) -> WatchdogDecision:
        if health.delivery_state == "UNKNOWN_DELIVERY":
            return WatchdogDecision(
                WatchdogAction.TECHNICAL_ALERT,
                ["delivery is uncertain; automatic resend is forbidden"],
            )
        if health.delivery_state == "SENDING" and (
            health.process_failed
            or health.heartbeat_at is None
            or now - health.heartbeat_at > self.heartbeat_timeout
        ):
            return WatchdogDecision(
                WatchdogAction.TECHNICAL_ALERT,
                ["sender failed after SENDING; mark UNKNOWN_DELIVERY"],
            )
        if not health.fencing_valid:
            return self._failover_or_block(standby_fresh, "fencing token lost")
        if health.process_failed:
            return self._failover_or_block(standby_fresh, "process failed")
        if health.heartbeat_at is None or now - health.heartbeat_at > self.heartbeat_timeout:
            return self._failover_or_block(standby_fresh, "heartbeat expired")
        if (
            health.active_request_deadline_at is not None
            and now > health.active_request_deadline_at
        ):
            return self._failover_or_block(standby_fresh, "active request hard deadline exceeded")
        if (
            health.last_progress_at is None
            or now - health.last_progress_at > self.progress_timeout
        ):
            if (
                health.active_request_deadline_at is None
                or now > health.active_request_deadline_at
            ):
                return self._failover_or_block(standby_fresh, "micro progress expired")
        if health.estimated_finish_at and health.estimated_finish_at > sla_deadline:
            return WatchdogDecision(WatchdogAction.DEGRADE_NOW, ["healthy process risks SLA"])
        return WatchdogDecision(WatchdogAction.NO_ACTION, ["healthy and progressing"])

    @staticmethod
    def _failover_or_block(standby_fresh: bool, reason: str) -> WatchdogDecision:
        if not standby_fresh:
            return WatchdogDecision(WatchdogAction.RUNTIME_BLOCKED, [reason, "standby freshness unknown"])
        return WatchdogDecision(WatchdogAction.START_FAILOVER, [reason])
