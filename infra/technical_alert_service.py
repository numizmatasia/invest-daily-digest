from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any

from storage.repository import MemoryRepository


_SECRET_KEY = re.compile(r"token|password|secret|session|sid|chat_id", re.IGNORECASE)
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_TELEGRAM_TOKEN = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")


class TechnicalAlertService:
    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    def create(
        self,
        *,
        alert_type: str,
        logical_window: str,
        root_cause: str,
        severity: str,
        details: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        dedup_material = f"{alert_type}:{logical_window}:{root_cause}:{severity}"
        dedup_key = sha256(dedup_material.encode("utf-8")).hexdigest()
        payload = {
            "alert_type": alert_type,
            "logical_window": logical_window,
            "severity": severity,
            "details": self.redact(details),
        }
        return self.repository.create_alert(dedup_key, payload)

    @classmethod
    def redact(cls, value: Any) -> Any:
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                result[key] = "[REDACTED]" if _SECRET_KEY.search(str(key)) else cls.redact(item)
            return result
        if isinstance(value, list):
            return [cls.redact(item) for item in value]
        if isinstance(value, str):
            value = _BEARER.sub("Bearer [REDACTED]", value)
            value = _TELEGRAM_TOKEN.sub("[REDACTED_TELEGRAM_TOKEN]", value)
            return value
        return deepcopy(value)
