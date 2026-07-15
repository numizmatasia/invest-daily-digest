from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def t0() -> datetime:
    return datetime(2026, 7, 15, 1, 0, tzinfo=timezone.utc)


@pytest.fixture
def portfolio_raw() -> dict:
    return {
        "Freedom": {"SPY": 50.0, "VT": 25.0, "XLE": 25.0},
        "Paidax": {"MU": 50.0, "VT": 50.0},
    }


@pytest.fixture
def source_catalog() -> dict:
    return {"version": "sources-test-v1", "mandatory_sources": ["official"]}
