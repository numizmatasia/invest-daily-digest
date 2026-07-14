from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from infra.types import DeliveryState
from storage.repository import MemoryRepository


class DeliveryStore:
    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    def prepare(
        self,
        *,
        scope_key: str,
        delivery_key: str,
        digest_id: str,
        run_id: str,
        token: int,
        text: str,
        now: datetime,
    ) -> dict:
        content_hash = sha256(text.encode("utf-8")).hexdigest()
        return self.repository.create_delivery(
            scope_key=scope_key,
            delivery_key=delivery_key,
            digest_id=digest_id,
            run_id=run_id,
            token=token,
            content_hash=content_hash,
            now=now,
        )

    def reserve(self, delivery_key: str, run_id: str, token: int, now: datetime) -> dict:
        return self.repository.transition_delivery(
            delivery_key=delivery_key,
            expected={DeliveryState.PREPARED.value, DeliveryState.DEFINITIVE_FAILED.value},
            new_state=DeliveryState.RESERVED.value,
            run_id=run_id,
            token=token,
            now=now,
        )

    def start_sending(self, delivery_key: str, run_id: str, token: int, now: datetime) -> dict:
        return self.repository.transition_delivery(
            delivery_key=delivery_key,
            expected={DeliveryState.RESERVED.value},
            new_state=DeliveryState.SENDING.value,
            run_id=run_id,
            token=token,
            now=now,
        )

    def mark_sent(
        self,
        delivery_key: str,
        run_id: str,
        token: int,
        message_id: int,
        now: datetime,
    ) -> dict:
        return self.repository.transition_delivery(
            delivery_key=delivery_key,
            expected={DeliveryState.SENDING.value},
            new_state=DeliveryState.SENT.value,
            run_id=run_id,
            token=token,
            now=now,
            message_id=message_id,
        )

    def mark_unknown(
        self,
        delivery_key: str,
        run_id: str,
        token: int,
        reason: str,
        now: datetime,
    ) -> dict:
        return self.repository.transition_delivery(
            delivery_key=delivery_key,
            expected={DeliveryState.SENDING.value},
            new_state=DeliveryState.UNKNOWN_DELIVERY.value,
            run_id=run_id,
            token=token,
            now=now,
            unknown_reason=reason,
        )
