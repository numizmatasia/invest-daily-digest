from __future__ import annotations

from typing import Any

from storage.repository import MemoryRepository


class ConfigSnapshotService:
    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    def capture(
        self,
        *,
        portfolio: dict[str, Any],
        watchlist: dict[str, Any],
        user_limits: dict[str, Any],
        source_catalog: dict[str, Any],
        rules_version: str,
    ) -> dict[str, Any]:
        payload = {
            "portfolio": portfolio,
            "watchlist": watchlist,
            "user_limits": user_limits,
            "source_catalog": source_catalog,
            "rules_version": rules_version,
        }
        return self.repository.create_config_snapshot(payload)
