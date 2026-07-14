from __future__ import annotations

from datetime import datetime
from typing import Any

from storage.repository import MemoryRepository


class CheckpointStore:
    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    def save_completed(
        self,
        *,
        scope_key: str,
        run_id: str,
        token: int,
        checkpoint_key: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        return self.repository.save_checkpoint(
            scope_key=scope_key,
            run_id=run_id,
            token=token,
            now=now,
            checkpoint_key=checkpoint_key,
            state="COMPLETED",
            payload=payload,
        )

    def pending(self, scope_key: str, all_keys: list[str]) -> list[str]:
        completed = self.repository.completed_checkpoint_keys(scope_key)
        return [key for key in all_keys if key not in completed]
