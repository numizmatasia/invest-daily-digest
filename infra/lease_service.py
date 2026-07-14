from __future__ import annotations

from datetime import datetime, timedelta

from storage.repository import LostFenceError, MemoryRepository


class LeaseService:
    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    @staticmethod
    def scope(job_type: str, logical_window: str) -> str:
        return f"{job_type}:{logical_window}"

    def acquire(
        self,
        *,
        job_type: str,
        logical_window: str,
        run_id: str,
        now: datetime,
        ttl_seconds: int = 300,
    ):
        return self.repository.acquire_lease(
            scope_key=self.scope(job_type, logical_window),
            job_type=job_type,
            logical_window=logical_window,
            owner_run_id=run_id,
            now=now,
            ttl=timedelta(seconds=ttl_seconds),
        )

    def assert_current(self, *, scope_key: str, run_id: str, token: int, now: datetime) -> None:
        if not self.repository.verify_fence(scope_key, run_id, token, now):
            raise LostFenceError(scope_key)
