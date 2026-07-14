from copy import deepcopy

from infra.config_snapshot import ConfigSnapshotService


def _capture(service, portfolio):
    return service.capture(
        portfolio=portfolio,
        watchlist={"watchlist": []},
        user_limits={"minimum_plan": 400},
        source_catalog={"version": "1"},
        rules_version="v3.11",
    )


def test_config_hash_is_stable(repo):
    service = ConfigSnapshotService(repo)
    first = _capture(service, {"positions": ["SPY"]})
    second = _capture(service, {"positions": ["SPY"]})
    assert first["config_snapshot_id"] == second["config_snapshot_id"]


def test_portfolio_change_applies_to_new_snapshot_only(repo):
    service = ConfigSnapshotService(repo)
    portfolio = {"positions": ["SPY"]}
    first = _capture(service, portfolio)
    portfolio["positions"].append("CCJ")
    second = _capture(service, portfolio)
    assert first["payload"]["portfolio"] == {"positions": ["SPY"]}
    assert second["config_snapshot_id"] != first["config_snapshot_id"]
