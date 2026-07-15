from __future__ import annotations

from datetime import date

from storage.repository import MemoryRepository
from stage4.pipeline import run_shadow_morning
from tests.stage4_helpers import raw_item


def test_full_shadow_pipeline_uses_stage3_state_and_prepares_only(portfolio_raw, source_catalog, t0):
    repo = MemoryRepository()
    result = run_shadow_morning(
        repository=repo,
        logical_date=date(2026,7,15),
        now=t0,
        raw_items=[raw_item()],
        portfolio_raw=portfolio_raw,
        watchlist_raw=["MU"],
        source_catalog=source_catalog,
        source_results=[{"name":"official","ok":True}],
        rules_version="stage4-rules-v2",
    )
    assert result["events"]
    assert result["decision"].headline.startswith("Срочных торговых действий нет")
    assert "PORTFOLIO_FRESHNESS_NOT_VERIFIED" not in result["decision"].warnings
    assert result["delivery"]["state"] == "PREPARED"
    assert result["delivery"]["shadow_only"] is True
    assert result["delivery"]["telegram_send_called"] is False
    assert repo.snapshots
    assert repo.deliveries


def test_checked_in_unapproved_source_catalog_blocks_conclusion(portfolio_raw, t0):
    repo = MemoryRepository()
    result = run_shadow_morning(
        repository=repo,
        logical_date=date(2026,7,15),
        now=t0,
        raw_items=[raw_item()],
        portfolio_raw=portfolio_raw,
        watchlist_raw=[],
        source_catalog={"version":"UNAPPROVED","mandatory_sources":[]},
        source_results=[],
        rules_version="stage4-rules-v2",
    )
    assert result["coverage"].runtime_status == "RUNTIME_BLOCKED"
    assert result["decision"].headline.startswith("Персональный вывод ограничен")
