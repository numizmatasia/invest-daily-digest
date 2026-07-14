from __future__ import annotations

from datetime import datetime
from typing import Any

from infra.types import sha256_json
from storage.repository import MemoryRepository


class RawJournalService:
    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    def append(
        self,
        *,
        source_id: str,
        independence_group: str,
        title: str,
        raw_payload: dict[str, Any],
        observed_at: datetime,
        upstream_id: str | None = None,
        source_published_at: datetime | None = None,
        source_time_quality: str = "RELIABLE",
        language: str = "en",
        parser_version: str = "stage3-v1",
    ) -> tuple[dict[str, Any], bool]:
        if source_time_quality not in {"RELIABLE", "UNRELIABLE", "ABSENT"}:
            raise ValueError("invalid source_time_quality")
        if source_time_quality == "ABSENT" and source_published_at is not None:
            raise ValueError("ABSENT source time requires null source_published_at")
        if source_time_quality == "RELIABLE" and source_published_at is None:
            raise ValueError("RELIABLE source time requires source_published_at")
        content_hash = sha256_json(raw_payload)
        item = {
            "source_id": source_id,
            "source_independence_group": independence_group,
            "upstream_id": upstream_id,
            "canonical_url": raw_payload.get("url"),
            "title": title,
            "body_text": raw_payload.get("body"),
            "language": language,
            "source_published_at": source_published_at,
            "source_time_quality": source_time_quality,
            "effective_at": raw_payload.get("effective_at"),
            "market_observed_at": raw_payload.get("market_observed_at"),
            "observed_at": observed_at,
            "content_hash": content_hash,
            "parser_version": parser_version,
            "raw_payload": raw_payload,
        }
        return self.repository.append_raw(item)
