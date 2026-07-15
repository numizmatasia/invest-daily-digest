from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from stage4.models import BrokerPortfolio, BrokerPosition, PortfolioSnapshot


class PortfolioBlockedError(RuntimeError):
    pass


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def load_current_portfolio(data: dict[str, Any]) -> PortfolioSnapshot:
    """Load the repository's frozen percentage-based Freedom/Paidax format.

    The adapter does not invent quantity or price. The declared broker weights are
    preserved independently, so a ticker held at both brokers cannot overwrite
    either position.
    """
    if not isinstance(data, dict):
        raise PortfolioBlockedError("PORTFOLIO_NOT_OBJECT")
    expected = ("Freedom", "Paidax")
    missing = [broker for broker in expected if broker not in data]
    if missing:
        raise PortfolioBlockedError("MISSING_BROKER:" + ",".join(missing))

    brokers: dict[str, BrokerPortfolio] = {}
    warnings: list[str] = [
        "WEIGHTS_ARE_DECLARED_PERCENTAGES_NOT_QUANTITY_X_PRICE",
        "PORTFOLIO_FRESHNESS_UNVERIFIED_CURRENT_FORMAT_HAS_NO_AS_OF",
    ]
    for broker in expected:
        raw_positions = data.get(broker)
        if not isinstance(raw_positions, dict) or not raw_positions:
            raise PortfolioBlockedError(f"INVALID_BROKER_PORTFOLIO:{broker}")
        positions: list[BrokerPosition] = []
        seen: set[str] = set()
        for raw_ticker, raw_weight in raw_positions.items():
            ticker = str(raw_ticker).strip().upper()
            if not ticker or ticker in seen:
                raise PortfolioBlockedError(f"INVALID_OR_DUPLICATE_TICKER:{broker}:{ticker}")
            seen.add(ticker)
            try:
                weight = float(raw_weight)
            except (TypeError, ValueError) as exc:
                raise PortfolioBlockedError(f"INVALID_WEIGHT:{broker}:{ticker}") from exc
            if weight < 0 or weight > 100:
                raise PortfolioBlockedError(f"OUT_OF_RANGE_WEIGHT:{broker}:{ticker}")
            positions.append(BrokerPosition(broker=broker, ticker=ticker, declared_weight_pct=weight))
        total = sum(item.declared_weight_pct for item in positions)
        if not 95 <= total <= 105:
            warnings.append(f"BROKER_WEIGHT_TOTAL_OUTSIDE_TOLERANCE:{broker}:{total:.4f}")
        brokers[broker] = BrokerPortfolio(broker=broker, positions=tuple(positions))

    return PortfolioSnapshot(
        version="portfolio_sha256:" + _canonical_hash(data),
        brokers=brokers,
        source_format="BROKER_DECLARED_WEIGHT_PERCENTAGES_V1",
        freshness_status="UNVERIFIED",
        warnings=tuple(warnings),
    )


def load_watchlist(data: Any) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    warnings: list[str] = []
    tickers: list[str] = []
    if isinstance(data, list):
        values = data
    elif isinstance(data, dict):
        values = data.get("tickers", data.get("watchlist", []))
    else:
        warnings.append("WATCHLIST_INVALID_IGNORED")
        values = []
    if not isinstance(values, list):
        warnings.append("WATCHLIST_INVALID_IGNORED")
        values = []
    for value in values:
        if isinstance(value, dict):
            raw_ticker = value.get("ticker")
        else:
            raw_ticker = value
        ticker = str(raw_ticker or "").strip().upper()
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    version = "watchlist_sha256:" + _canonical_hash(data)
    return tuple(tickers), tuple(warnings), version
