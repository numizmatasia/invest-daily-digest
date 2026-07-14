from pathlib import Path


def test_migration_contains_all_required_tables():
    sql = Path("storage/migrations/0001_stage3_foundation.sql").read_text(encoding="utf-8")
    tables = [
        "ia_raw_items", "ia_event_versions", "ia_config_snapshots",
        "ia_calendar_windows", "ia_snapshots", "ia_runs",
        "ia_execution_leases", "ia_delivery_records",
        "ia_watchdog_checks", "ia_technical_alerts",
    ]
    for table in tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql


def test_migration_declares_unknown_delivery_and_fencing():
    sql = Path("storage/migrations/0001_stage3_foundation.sql").read_text(encoding="utf-8")
    assert "UNKNOWN_DELIVERY" in sql
    assert "fencing_token" in sql
