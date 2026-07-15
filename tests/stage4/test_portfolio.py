from __future__ import annotations

from stage4.portfolio_loader import load_current_portfolio, load_watchlist


def test_current_repository_portfolio_format_is_supported(portfolio_raw):
    snapshot = load_current_portfolio(portfolio_raw)
    assert snapshot.source_format == "BROKER_DECLARED_WEIGHT_PERCENTAGES_V1"
    assert snapshot.freshness_status == "DECLARED_CURRENT"
    assert "PORTFOLIO_COMPOSITION_DECLARED_CURRENT_UNTIL_USER_REPORTS_CHANGE" in snapshot.warnings
    assert set(snapshot.brokers) == {"Freedom", "Paidax"}


def test_same_ticker_remains_separate_by_broker(portfolio_raw):
    snapshot = load_current_portfolio(portfolio_raw)
    assert snapshot.broker_weight("Freedom", "VT") == 25.0
    assert snapshot.broker_weight("Paidax", "VT") == 50.0


def test_adapter_does_not_invent_quantity_or_price(portfolio_raw):
    snapshot = load_current_portfolio(portfolio_raw)
    assert "WEIGHTS_ARE_LAST_DECLARED_NOT_LIVE_MARKET_WEIGHTS" in snapshot.warnings
    assert not hasattr(next(iter(snapshot.brokers["Freedom"].positions)), "quantity")


def test_invalid_watchlist_does_not_stop_portfolio():
    tickers, warnings, version = load_watchlist("broken")
    assert tickers == ()
    assert warnings == ("WATCHLIST_INVALID_IGNORED",)
    assert version.startswith("watchlist_sha256:")


def test_current_repository_watchlist_object_format_is_supported():
    raw = {
        "watchlist": [
            {"ticker": "AVGO", "name": "Broadcom", "status": "WATCH"},
            {"ticker": "SKHY", "name": "SK Hynix", "status": "WATCH"},
        ]
    }
    tickers, warnings, version = load_watchlist(raw)
    assert tickers == ("AVGO", "SKHY")
    assert warnings == ()
    assert version.startswith("watchlist_sha256:")
