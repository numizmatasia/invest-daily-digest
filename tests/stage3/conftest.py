from __future__ import annotations

from datetime import datetime, timezone

import pytest

from storage.repository import MemoryRepository


@pytest.fixture
def repo() -> MemoryRepository:
    return MemoryRepository()


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 7, 13, 1, 0, tzinfo=timezone.utc)
