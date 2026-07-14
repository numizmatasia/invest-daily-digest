from datetime import timedelta

import pytest

from infra.clock_guard import ClockGuard
from infra.technical_alert_service import TechnicalAlertService


def test_technical_alert_is_deduplicated(repo):
    service = TechnicalAlertService(repo)
    first, created1 = service.create(alert_type="SLA", logical_window="2026-07-13", root_cause="late", severity="CRITICAL", details={"message": "late"})
    second, created2 = service.create(alert_type="SLA", logical_window="2026-07-13", root_cause="late", severity="CRITICAL", details={"message": "late again"})
    assert created1 is True and created2 is False
    assert first["alert_id"] == second["alert_id"]


def test_secrets_are_redacted(repo):
    service = TechnicalAlertService(repo)
    alert, _ = service.create(alert_type="AUTH", logical_window="x", root_cause="bad", severity="ERROR", details={"telegram_bot_token": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd", "nested": {"password": "secret"}, "text": "Bearer abc.def"})
    rendered = str(alert)
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in rendered
    assert "secret" not in rendered
    assert "abc.def" not in rendered


def test_acceptable_clock_skew(now):
    result = ClockGuard(2000).check(now + timedelta(milliseconds=1500), now)
    assert result.acceptable is True


def test_excessive_clock_skew_blocks_sensitive_operation(now):
    with pytest.raises(RuntimeError):
        ClockGuard(2000).assert_acceptable(now + timedelta(seconds=3), now)


def test_alert_severity_change_creates_new_alert(repo):
    service = TechnicalAlertService(repo)
    _, first = service.create(
        alert_type="SOURCE", logical_window="x", root_cause="down",
        severity="WARNING", details={"message": "down"},
    )
    _, second = service.create(
        alert_type="SOURCE", logical_window="x", root_cause="down",
        severity="CRITICAL", details={"message": "still down"},
    )
    assert first is True and second is True
