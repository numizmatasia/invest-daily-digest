from __future__ import annotations

import os
from pathlib import Path

import pytest

from storage.database import PsycopgDatabase
from storage.migrate import MigrationRunner


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


def test_postgres_migration_and_health_check():
    db = PsycopgDatabase(os.environ["TEST_DATABASE_URL"])
    runner = MigrationRunner(db)
    applied = runner.apply(Path("storage/migrations/0001_stage3_foundation.sql"), "stage3-v1.0")
    assert applied is True
    assert db.health_check() is True


def test_postgres_migration_is_rerunnable():
    db = PsycopgDatabase(os.environ["TEST_DATABASE_URL"])
    runner = MigrationRunner(db)
    path = Path("storage/migrations/0001_stage3_foundation.sql")
    runner.apply(path, "stage3-v1.0")
    applied_again = runner.apply(path, "stage3-v1.0")
    assert applied_again is False
    assert db.health_check() is True
