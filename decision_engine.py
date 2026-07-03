ASSET_CLASSES = {
    "Американские акции": ["SPY", "VT", "QQQM", "IXUS", "SPYM", "SPYG"],
    "Уран и ядерная энергетика": ["CCJ", "UROY", "KZAPD"],
    "Энергетика": ["XLE"],
    "ИИ и полупроводники": ["NVDA", "AMAT", "VRT", "MU", "AVGO", "SKHY", "GOOGL", "META", "AMZN"],
    "Драгоценные металлы": ["SIVR", "PSLV", "GLD"],
    "Крипта": ["IBIT"],
    "Прочее": ["CORE", "PL"],
}

LARGE_POSITION_LIMIT = 15
MEDIUM_POSITION_LIMIT = 7
DEFAULT_MONTHLY_TARGET_USD = 400


def get_all_portfolio_tickers(portfolio_data):
    tickers = set()
    for positions in portfolio_data.values():
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
    if weight >= LARGE_POSITION_LIMIT:
        return "large"
    if weight >= MEDIUM_POSITION_LIMIT:
        return "medium"
    return "small"


def get_current_cash_month(cash_log):
    if not cash_log:
        return {
            "target_min_usd": DEFAULT_MONTHLY_TARGET_USD,
            "deposited_usd": 0,
            "invested_usd": 0,
            "cash_left_usd": 0,
        }
    latest_month = sorted(cash_log.keys())[-1]
    month_data = cash_log.get(latest_month, {})
    return {
        "month": latest_month,
        "target_min_usd": month_data.get("target_min_usd", DEFAULT_MONTHLY_TARGET_USD),
        "deposited_usd": month_data.get("deposited_usd", 0),
        "invested_usd": month_data.get("invested_usd", 0),
        "cash_left_usd": month_data.get("cash_left_usd", 0),
    }


def get_asset_class_for_ticker(ticker):
    ticker = ticker.upper()
    for asset_class, tickers in ASSET_CLASSES.items():
        if ticker in tickers:
            return asset_class
    return "Прочее"


def calculate_asset_class_weights(portfolio_data):
    class_weights = {}
    unknown_positions = {}

    for portfolio_name, positions in portfolio_data.items():
        for ticker, weight in positions.items():
            asset_class = get_asset_class_for_ticker(ticker)
            if weight is None:
                unknown_positions.setdefault(asset_class, []).append(ticker)
                continue
            class_weights[asset_class] = class_weights.get(asset_class, 0) + float(weight)

    return class_weights, unknown_positions


def make_decisions(events, portfolio_data):
    """Оставлено для совместимости с main.py старых версий."""
    decisions = []
    portfolio_tickers = get_all_portfolio_tickers(portfolio_data)

    for event in events:
        related_tickers = [ticker.upper() for ticker in event.get("portfolio_links", [])]
        affected_tickers = [ticker for ticker in related_tickers if ticker in portfolio_tickers]

        if not affected_tickers:
            decisions.append({
                "event": event.get("title", ""),
                "action": "observe",
                "reason": "Событие не имеет прямой связи с текущими позициями портфеля.",
                "tickers": related_tickers,
                "importance": event.get("importance", 0),
            })
            continue

        for ticker in affected_tickers:
            portfolio_name, weight = get_position_weight(portfolio_data, ticker)
            size = classify_position_size(weight)

            if size == "large":
                action = "hold_not_add"
                reason = f"{ticker} уже занимает крупную долю в портфеле {portfolio_name} ({weight}%). Держать, но не наращивать без сильной просадки."
            elif size == "medium":
                action = "hold"
                reason = f"{ticker} уже есть в портфеле {portfolio_name} ({weight}%). Новость важна, но это не автоматический сигнал к покупке."
            elif size == "small":
                action = "watch"
                reason = f"{ticker} есть в портфеле {portfolio_name}, но доля небольшая ({weight}%). Можно наблюдать, но без покупки на эмоциях."
            else:
                action = "watch"
                reason = f"{ticker} есть в портфеле {portfolio_name}, но размер позиции неизвестен. Без размера позиции нельзя давать точную рекомендацию."

            decisions.append({
                "event": event.get("title", ""),
                "action": action,
                "reason": reason,
                "tickers": [ticker],
                "importance": event.get("importance", 0),
            })

    return decisions


def make_daily_decision(events, portfolio_data, cash_log):
    class_weights, unknown_positions = calculate_asset_class_weights(portfolio_data)
    cash = get_current_cash_month(cash_log)

    strong_events = [event for event in events if event.get("importance", 0) >= 12]
    portfolio_tickers = get_all_portfolio_tickers(portfolio_data)

    affected_tickers = set()
    for event in events:
        for ticker in event.get("portfolio_links", []):
            ticker = ticker.upper()
            if ticker in portfolio_tickers:
                affected_tickers.add(ticker)

    large_classes = {
        name: weight for name, weight in class_weights.items()
        if weight >= LARGE_POSITION_LIMIT
    }

    asset_class_actions = []
    for asset_class, weight in sorted(class_weights.items(), key=lambda item: item[1], reverse=True):
        if weight >= LARGE_POSITION_LIMIT:
            action = "Держать, не наращивать"
            reason = "доля уже крупная"
        elif weight >= MEDIUM_POSITION_LIMIT:
            action = "Держать"
            reason = "доля заметная, докупка только при сильном сигнале"
        else:
            action = "Наблюдать"
            reason = "доля небольшая, но сильного сигнала к покупке нет"

        asset_class_actions.append({
            "asset_class": asset_class,
            "weight": round(weight, 2),
            "action": action,
            "reason": reason,
        })

    for asset_class, tickers in unknown_positions.items():
        asset_class_actions.append({
            "asset_class": asset_class,
            "weight": None,
            "action": "Наблюдать",
            "reason": "размер позиций неизвестен, точную рекомендацию дать нельзя",
            "unknown_tickers": tickers,
        })

    cash_left = cash.get("cash_left_usd", 0)
    deposited = cash.get("deposited_usd", 0)
    target = cash.get("target_min_usd", DEFAULT_MONTHLY_TARGET_USD)
    missing_deposit = max(target - deposited, 0)

    # Покупку разрешаем только при сильном новом событии, которое не раздувает уже крупную долю.
    has_strong_new_opportunity = False
    opportunity_note = "Сильных новых идей для покупки сегодня нет."

    for event in strong_events:
        linked = [ticker.upper() for ticker in event.get("portfolio_links", [])]
        linked_in_portfolio = [ticker for ticker in linked if ticker in portfolio_tickers]
        if not linked_in_portfolio and event.get("id") == "scout_events":
            has_strong_new_opportunity = True
            opportunity_note = "Есть сильное новое событие вне текущего портфеля, но нужна отдельная проверка перед покупкой."
            break

    if has_strong_new_opportunity and cash_left > 0:
        final_action = "BUY_CANDIDATE"
        action_text = "Рассмотреть покупку"
        recommended_purchase_usd = min(cash_left, 200)
        main_reason = "Есть сильная новая идея и свободный инвестиционный бюджет. Перед покупкой нужна ручная проверка тикера."
    else:
        final_action = "WAIT"
        action_text = "Ждать"
        recommended_purchase_usd = 0
        if large_classes:
            main_reason = "Крупные доли уже есть, новых сильных идей алгоритм не нашел. Покупка сейчас не обязательна."
        else:
            main_reason = "Есть важные новости, но они не дают достаточно сильного сигнала для покупки сегодня."

    if missing_deposit > 0:
        deposit_note = f"До минимального месячного ориентира не хватает {missing_deposit} $. Деньги можно довнести по плану, но не тратить без сильной идеи."
    else:
        deposit_note = "Минимальный месячный ориентир по пополнению выполнен."

    return {
        "final_action": final_action,
        "action_text": action_text,
        "recommended_purchase_usd": recommended_purchase_usd,
        "main_reason": main_reason,
        "cash": cash,
        "missing_deposit_usd": missing_deposit,
        "deposit_note": deposit_note,
        "asset_class_actions": asset_class_actions,
        "strong_events_count": len(strong_events),
        "affected_tickers": sorted(affected_tickers),
        "opportunity_note": opportunity_note,
    }


def format_daily_decision_for_prompt(daily_decision):
    cash = daily_decision["cash"]
    lines = []

    lines.append("РЕШЕНИЕ НА СЕГОДНЯ")
    lines.append(f"Итоговое действие: {daily_decision['action_text']}")
    lines.append(f"Рекомендуемая покупка сегодня: {daily_decision['recommended_purchase_usd']} $")
    lines.append(f"Причина: {daily_decision['main_reason']}")
    lines.append("")

    lines.append("ИНВЕСТИЦИОННЫЙ БЮДЖЕТ")
    lines.append(f"Месяц: {cash.get('month', 'текущий')}")
    lines.append(f"Минимальный ориентир пополнения: {cash.get('target_min_usd', DEFAULT_MONTHLY_TARGET_USD)} $")
    lines.append(f"Внесено в этом месяце: {cash.get('deposited_usd', 0)} $")
    lines.append(f"Уже инвестировано: {cash.get('invested_usd', 0)} $")
    lines.append(f"Свободный кэш: {cash.get('cash_left_usd', 0)} $")
    lines.append(f"Комментарий: {daily_decision['deposit_note']}")
    lines.append("")

    lines.append("РЕШЕНИЯ ПО КЛАССАМ АКТИВОВ")
    for item in daily_decision["asset_class_actions"]:
        if item.get("weight") is None:
            weight_text = "доля неизвестна"
        else:
            weight_text = f"{item['weight']}%"
        lines.append(f"{item['asset_class']}: {item['action']} ({weight_text}). Причина: {item['reason']}.")

    lines.append("")
    lines.append("ВОЗМОЖНОСТИ")
    lines.append(daily_decision["opportunity_note"])

    return "\n".join(lines)


def format_decisions_for_prompt(decisions):
    if not decisions:
        return "Алгоритм не нашел решений, требующих действий."

    lines = []
    for decision in decisions:
        lines.append(f"Событие: {decision['event']}")
        lines.append(f"Действие алгоритма: {decision['action']}")
        lines.append(f"Тикеры: {', '.join(decision['tickers']) if decision['tickers'] else 'нет'}")
        lines.append(f"Причина: {decision['reason']}")
        lines.append("")

    return "\n".join(lines)
