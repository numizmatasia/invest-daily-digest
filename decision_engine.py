from datetime import datetime


ASSET_CLASSES = {
    "american_equities": {
        "name": "Американские акции и ETF",
        "tickers": ["SPY", "VT", "QQQM", "IXUS", "SPYM", "SPYG"],
    },
    "uranium_nuclear": {
        "name": "Уран и ядерная энергетика",
        "tickers": ["KZAPD", "CCJ", "UROY"],
    },
    "energy": {
        "name": "Энергетика",
        "tickers": ["XLE"],
    },
    "precious_metals": {
        "name": "Драгоценные металлы",
        "tickers": ["SIVR", "PSLV", "GLD"],
    },
    "crypto": {
        "name": "Крипто",
        "tickers": ["IBIT"],
    },
    "ai_semiconductors": {
        "name": "ИИ и полупроводники",
        "tickers": ["NVDA", "AMAT", "VRT", "MU", "AVGO", "SKHY", "GOOGL", "META", "AMZN"],
    },
    "other": {
        "name": "Прочие активы",
        "tickers": ["CORE", "PL"],
    },
}


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
    if weight >= 15:
        return "large"
    if weight >= 7:
        return "medium"
    return "small"


def make_decisions(events, portfolio_data):
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
                reason = f"{ticker} есть в портфеле {portfolio_name}, но доля небольшая ({weight}%). Наблюдать без покупки на эмоциях."
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


def _latest_cash_month(cash_log):
    if not cash_log:
        current = datetime.utcnow().strftime("%Y-%m")
        return current, {"target_min_usd": 400, "deposited_usd": 0, "invested_usd": 0, "cash_left_usd": 0}
    month = sorted(cash_log.keys())[-1]
    return month, cash_log.get(month, {})


def _class_weight(portfolio_data, class_tickers):
    known_weight = 0.0
    unknown_tickers = []
    held_tickers = []

    for portfolio_name, positions in portfolio_data.items():
        for ticker, weight in positions.items():
            if ticker.upper() in class_tickers:
                held_tickers.append(ticker.upper())
                if weight is None:
                    unknown_tickers.append(ticker.upper())
                else:
                    known_weight += float(weight)

    return round(known_weight, 2), sorted(set(unknown_tickers)), sorted(set(held_tickers))


def build_asset_class_summary(portfolio_data):
    result = []

    for class_id, class_data in ASSET_CLASSES.items():
        tickers = [ticker.upper() for ticker in class_data["tickers"]]
        weight, unknown, held = _class_weight(portfolio_data, tickers)

        if not held:
            continue

        if weight >= 20:
            action = "Держать, не увеличивать"
            reason = "доля уже крупная"
        elif weight >= 7:
            action = "Держать"
            reason = "доля уже заметная"
        elif unknown and weight == 0:
            action = "Наблюдать"
            reason = "размер позиций неизвестен"
        else:
            action = "Наблюдать"
            reason = "сильного сигнала к покупке нет"

        result.append({
            "class_id": class_id,
            "name": class_data["name"],
            "weight": weight,
            "unknown_tickers": unknown,
            "held_tickers": held,
            "action": action,
            "reason": reason,
        })

    return result


def build_daily_decision(events, decisions, portfolio_data, cash_log):
    month, cash = _latest_cash_month(cash_log)

    target_min = int(cash.get("target_min_usd", 400) or 400)
    deposited = int(cash.get("deposited_usd", 0) or 0)
    invested = int(cash.get("invested_usd", 0) or 0)
    cash_left = int(cash.get("cash_left_usd", 0) or 0)
    missing = max(target_min - deposited, 0)

    strong_events = [event for event in events if event.get("importance", 0) >= 12]
    scout_events = [event for event in events if event.get("id") == "scout_events" and event.get("importance", 0) >= 10]
    has_buy_candidate = bool(scout_events)

    large_position_count = sum(1 for decision in decisions if decision.get("action") == "hold_not_add")

    if has_buy_candidate and cash_left > 0:
        action = "BUY_SMALL"
        action_ru = "✅ Купить небольшую позицию"
        purchase_amount = min(cash_left, 200)
        why = "Алгоритм нашел новую идею и есть свободный кэш, но покупка должна быть ограниченной."
    else:
        action = "WAIT"
        action_ru = "⏳ Ждать"
        purchase_amount = 0
        if large_position_count:
            why = "В портфеле уже есть крупные доли, а сильных новых идей для покупки сегодня нет."
        else:
            why = "Алгоритм не обнаружил идеи, достаточно сильной для покупки сегодня."

    opportunities = "Сильных новых идей для покупки сегодня нет."
    if scout_events:
        opportunities = "Есть потенциальные события для наблюдения, но они требуют дополнительного подтверждения перед покупкой."

    return {
        "action": action,
        "action_ru": action_ru,
        "purchase_amount_usd": purchase_amount,
        "why": why,
        "budget": {
            "month": month,
            "target_min_usd": target_min,
            "deposited_usd": deposited,
            "invested_usd": invested,
            "cash_left_usd": cash_left,
            "missing_to_target_usd": missing,
        },
        "strong_event_count": len(strong_events),
        "asset_classes": build_asset_class_summary(portfolio_data),
        "opportunities": opportunities,
        "do_not_do": [
            "Не совершать покупки активов, если рекомендованная сумма на сегодня равна 0 $.",
            "Не наращивать крупные позиции без сильной просадки.",
            "Не тратить свободный кэш без сильной идеи.",
        ],
    }


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


def format_daily_decision_for_prompt(daily_decision):
    budget = daily_decision["budget"]
    lines = [
        "ФИНАЛЬНОЕ РЕШЕНИЕ АЛГОРИТМА:",
        f"Действие сегодня: {daily_decision['action_ru']}",
        f"Сумма покупки сегодня: {daily_decision['purchase_amount_usd']} $",
        f"Причина: {daily_decision['why']}",
        "",
        "БЮДЖЕТ:",
        f"Месяц: {budget['month']}",
        f"Минимальный ориентир пополнения: {budget['target_min_usd']} $",
        f"Внесено: {budget['deposited_usd']} $",
        f"Инвестировано: {budget['invested_usd']} $",
        f"Свободный кэш: {budget['cash_left_usd']} $",
        f"Не хватает до ориентира: {budget['missing_to_target_usd']} $",
        "",
        "КЛАССЫ АКТИВОВ:",
    ]

    for item in daily_decision["asset_classes"]:
        weight_text = f"{item['weight']}%" if item["weight"] else "размер неизвестен"
        unknown = ""
        if item["unknown_tickers"]:
            unknown = f"; неизвестные размеры: {', '.join(item['unknown_tickers'])}"
        lines.append(f"- {item['name']}: {weight_text}; {item['action']}; причина: {item['reason']}{unknown}")

    lines.extend([
        "",
        "НОВЫЕ ВОЗМОЖНОСТИ:",
        daily_decision["opportunities"],
        "",
        "ЧТО НЕ ДЕЛАТЬ:",
    ])

    for item in daily_decision["do_not_do"]:
        lines.append(f"- {item}")

    return "\n".join(lines)


def format_compact_report(daily_decision):
    budget = daily_decision["budget"]

    asset_lines = []
    for item in daily_decision.get("asset_classes", []):
        if item.get("unknown_tickers") and item.get("weight", 0) == 0:
            asset_lines.append(f"• {item['name']}: наблюдать, размер позиций неизвестен.")
        elif item.get("weight", 0) >= 20:
            asset_lines.append(f"• {item['name']}: {item['weight']}% — держать, не увеличивать.")
        elif item.get("weight", 0) >= 7:
            asset_lines.append(f"• {item['name']}: {item['weight']}% — держать.")
        else:
            asset_lines.append(f"• {item['name']}: {item['weight']}% — наблюдать.")

    if not asset_lines:
        asset_lines.append("• Существенных данных по классам активов нет.")

    if budget['missing_to_target_usd'] > 0:
        budget_text = (
            f"Минимальный ориентир на месяц: {budget['target_min_usd']} $. "
            f"Внесено: {budget['deposited_usd']} $. "
            f"До ориентира не хватает: {budget['missing_to_target_usd']} $. "
            "Пополнить можно по плану, но тратить деньги сегодня не нужно без сильной идеи."
        )
    else:
        budget_text = (
            f"Минимальный ориентир на месяц выполнен: {budget['deposited_usd']} $ из {budget['target_min_usd']} $. "
            f"Свободный кэш: {budget['cash_left_usd']} $."
        )

    lines = [
        "<b>📌 РЕШЕНИЕ НА СЕГОДНЯ</b>",
        daily_decision["action_ru"],
        "",
        "<b>Сумма покупки сегодня:</b>",
        f"{daily_decision['purchase_amount_usd']} $",
        "",
        "<b>Почему:</b>",
        daily_decision["why"],
        "",
        "<b>💰 Инвестиционный бюджет</b>",
        budget_text,
        "",
        "<b>📊 Портфель по классам активов</b>",
        *asset_lines[:6],
        "",
        "<b>🧭 Новые возможности</b>",
        daily_decision["opportunities"],
        "",
        "<b>🚫 Что сегодня НЕ делать</b>",
    ]

    for i, item in enumerate(daily_decision.get("do_not_do", [])[:3], start=1):
        lines.append(f"{i}. {item}")

    lines.extend([
        "",
        "<b>Итог:</b>",
        "Сегодня действовать не нужно, если сумма покупки равна 0 $." if daily_decision['purchase_amount_usd'] == 0 else "Покупать только в пределах указанной суммы."
    ])

    return "\n".join(lines)
