from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from infra.types import sha256_json
from storage.repository import MemoryRepository


class EventStoreService:
    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    @staticmethod
    def build_event_id(
        *,
        entity_ids: Iterable[str],
        event_type: str,
        effective_key: str,
        key_facts: dict[str, Any],
    ) -> str:
        identity = {
            "entity_ids": sorted(set(entity_ids)),
            "event_type": event_type,
            "effective_key": effective_key,
            "key_facts": key_facts,
        }
        return f"evt_{sha256_json(identity)[:32]}"

    def upsert(
        self,
        *,
        event_id: str,
        event_type: str,
        canonical_payload: dict[str, Any],
        source_ref: str,
        now: datetime,
    ) -> tuple[int, bool]:
        canonical_hash = sha256_json(canonical_payload)
        event = self.repository.get_event(event_id)
        if event is None:
            self.repository.create_event(
                event_id=event_id,
                event_type=event_type,
                payload=canonical_payload,
                canonical_hash=canonical_hash,
                source_ref=source_ref,
                now=now,
            )
            return 1, True
        return self.repository.add_event_version(
            event_id=event_id,
            payload=canonical_payload,
            canonical_hash=canonical_hash,
            source_ref=source_ref,
            now=now,
        )
