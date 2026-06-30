def get_all_portfolio_tickers(portfolio_data):
    tickers = set()

    for portfolio_name, positions in portfolio_data.items():
        for ticker in positions.keys():
            tickers.add(ticker.upper())

    return tickers


def get_position_weight(portfolio_data, ticker):
    ticker = ticker.upper()

    for portfolio_name, positions in portfolio_data.items():
        for position_ticker, weight in positions.items():
            if position_ticker.upper() == ticker:
                return portfolio_name, weight

    return None, None


def classify_position_size(weight):
    if weight is None:
        return "unknown"

    if weight >= 15:
        return "large"

    if weight >= 7:
        return "medium"

    return "small"


def make_decisions(events, portfolio_data):
    decisions = []
    portfolio_tickers = get_all_portfolio_tickers(portfolio_data)

    for event in events:
        related_tickers = [
            ticker.upper()
            for ticker in event.get("portfolio_links", [])
        ]

        affected_tickers = [
            ticker for ticker in related_tickers
            if ticker in portfolio_tickers
        ]

        if not affected_tickers:
            decisions.append({
                "event": event.get("title", ""),
                "action": "observe",
                "reason": "Событие не имеет прямой связи с текущими позициями портфеля.",
                "tickers": related_tickers,
                "importance": event.get("importance", 0)
            })
            continue

        for ticker in affected_tickers:
            portfolio_name, weight = get_position_weight(portfolio_data, ticker)
            size = classify_position_size(weight)

            if size == "large":
                action = "hold_not_add"
                reason = (
                    f"{ticker} уже занимает крупную долю в портфеле {portfolio_name} "
                    f"({weight}%). Держать, но не наращивать без сильной просадки."
                )

            elif size == "medium":
                action = "hold"
                reason = (
                    f"{ticker} уже есть в портфеле {portfolio_name} "
                    f"({weight}%). Новость важна, но это не автоматический сигнал к покупке."
                )

            elif size == "small":
                action = "watch"
                reason = (
                    f"{ticker} есть в портфеле {portfolio_name}, но доля небольшая "
                    f"({weight}%). Можно наблюдать, но без покупки на эмоциях."
                )

            else:
                action = "watch"
                reason = (
                    f"{ticker} есть в портфеле {portfolio_name}, но размер позиции неизвестен. "
                    f"Без размера позиции нельзя давать точную рекомендацию."
                )

            decisions.append({
                "event": event.get("title", ""),
                "action": action,
                "reason": reason,
                "tickers": [ticker],
                "importance": event.get("importance", 0)
            })

    return decisions


def format_decisions_for_prompt(decisions):
    if not decisions:
        return "Алгоритм не нашел решений, требующих действий."

    lines = []

    for decision in decisions:
        lines.append(f"Событие: {decision['event']}")
        lines.append(f"Действие алгоритма: {decision['action']}")
        lines.append(f"Тикеры: {', '.join(decision['tickers']) if decision['tickers'] else 'нет'}")
        lines.append(f"Причина: {decision['reason']}")
        lines.append(f"Важность события: {decision['importance']}")
        lines.append("")

    return "\n".join(lines)
