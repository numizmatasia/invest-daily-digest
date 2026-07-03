from datetime import datetime


ASSET_CLASSES = {
    "us_equity_core": {
        "title": "Американские акции / широкий рынок",
        "tickers": ["SPY", "VT", "QQQM", "SPYM", "SPYG", "IXUS"],
    },
    "uranium": {
        "title": "Уран и ядерная энергетика",
        "tickers": ["CCJ", "UROY", "KZAPD"],
    },
    "energy": {
        "title": "Энергетика / нефть и газ",
        "tickers": ["XLE"],
    },
    "ai_semiconductors": {
        "title": "ИИ и полупроводники",
        "tickers": ["NVDA", "AMAT", "VRT", "MU", "AVGO", "SKHY", "PL"],
    },
    "precious_metals": {
        "title": "Золото и серебро",
        "tickers": ["GLD", "SIVR", "PSLV"],
    },
    "crypto": {
        "title": "Крипто / Bitcoin",
        "tickers": ["IBIT"],
    },
}


def get_current_month_key():
    return datetime.utcnow().strftime("%Y-%m")


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


def portfolio_sector_weight(portfolio_data, tickers):
    total = 0.0
    known = False
    ticker_set = {ticker.upper() for ticker in tickers}

    for positions in portfolio_data.values():
        for ticker, weight in positions.items():
            if ticker.upper() in ticker_set and isinstance(weight, (int, float)):
                total += float(weight)
                known = True

    return round(total, 2) if known else None


def get_cash_status(cash_log):
    month = get_current_month_key()
    data = cash_log.get(month)

    if not data and cash_log:
        month = sorted(cash_log.keys())[-1]
        data = cash_log.get(month, {})

    if not data:
        data = {
            "target_min_usd": 0,
            "deposited_usd": 0,
            "invested_usd": 0,
            "cash_left_usd": 0,
        }

    target = data.get("target_min_usd", 0) or 0
    deposited = data.get("deposited_usd", 0) or 0
    invested = data.get("invested_usd", 0) or 0
    cash_left = data.get("cash_left_usd", 0) or 0

    return {
        "month": month,
        "target_min_usd": target,
        "deposited_usd": deposited,
        "invested_usd": invested,
        "cash_left_usd": cash_left,
        "shortfall_usd": max(target - deposited, 0),
    }


def event_strength(events, asset_tickers):
    ticker_set = {ticker.upper() for ticker in asset_tickers}
    strength = 0
    matched_events = []

    for event in events:
        links = {ticker.upper() for ticker in event.get("portfolio_links", [])}
        if links & ticker_set:
            importance = event.get("importance", 0) or 0
            strength += importance
            matched_events.append(event.get("title", ""))

    return strength, matched_events[:3]


def action_from_weight_and_strength(weight, strength):
    if weight is None:
        if strength >= 18:
            return "WATCH", "нет точного размера позиции"
        return "NO_ACTION", "нет точного размера позиции и нет сильного сигнала"

    if weight >= 20:
        return "HOLD_NOT_ADD", "доля уже слишком крупная"

    if weight >= 15:
        return "HOLD_NOT_ADD", "доля уже крупная"

    if weight >= 7:
        if strength >= 22:
            return "HOLD", "позиция уже есть; новость подтверждает тренд, но не дает сигнала к докупке"
        return "HOLD", "позиция уже есть, но сигнал недостаточно сильный"

    if strength >= 28:
        return "WATCH", "сигнал сильный, но нужна отдельная проверка цены"

    return "WATCH", "наблюдать без покупки"


def build_asset_class_decisions(events, portfolio_data):
    results = []

    for class_id, class_data in ASSET_CLASSES.items():
        title = class_data["title"]
        tickers = class_data["tickers"]
        sector_weight = portfolio_sector_weight(portfolio_data, tickers)
        strength, matched_events = event_strength(events, tickers)

        if sector_weight is None and strength == 0:
            continue

        if sector_weight is not None:
            action, reason = action_from_weight_and_strength(sector_weight, strength)
        else:
            action = "WATCH" if strength >= 18 else "NO_ACTION"
            reason = "есть новостной сигнал, но нет позиции в портфеле"

        results.append({
            "class_id": class_id,
            "title": title,
            "tickers": tickers,
            "portfolio_weight": sector_weight,
            "event_strength": strength,
            "events": matched_events,
            "action": action,
            "reason": reason,
        })

    results.sort(key=lambda item: item["event_strength"], reverse=True)
    return results


def count_strong_new_ideas(events, portfolio_data):
    portfolio_tickers = get_all_portfolio_tickers(portfolio_data)
    ideas = []

    for event in events:
        links = {ticker.upper() for ticker in event.get("portfolio_links", [])}
        importance = event.get("importance", 0) or 0

        if links and links.isdisjoint(portfolio_tickers) and importance >= 20:
            ideas.append({
                "title": event.get("title", ""),
                "importance": importance,
                "tickers": sorted(links),
            })

    return ideas[:2]


def make_decisions(events, portfolio_data, cash_log=None):
    cash_log = cash_log or {}
    cash_status = get_cash_status(cash_log)
    asset_decisions = build_asset_class_decisions(events, portfolio_data)
    new_ideas = count_strong_new_ideas(events, portfolio_data)

    best_strength = max([item["event_strength"] for item in asset_decisions], default=0)
    has_large_hold_not_add = any(item["action"] == "HOLD_NOT_ADD" for item in asset_decisions)
    has_new_idea = len(new_ideas) > 0

    action_probability = min(max(best_strength * 3, 5), 85)

    final_action = "WAIT"
    recommended_purchase_usd = 0
    main_reason = "Нет сигнала, достаточно сильного для покупки сегодня."

    if has_new_idea and cash_status["cash_left_usd"] >= 100:
        final_action = "BUY_SMALL"
        recommended_purchase_usd = min(200, cash_status["cash_left_usd"])
        main_reason = "Есть новая сильная идея и свободный кэш, но размер покупки должен быть ограничен."
    elif has_new_idea and cash_status["cash_left_usd"] < 100:
        final_action = "WAIT"
        recommended_purchase_usd = 0
        main_reason = "Есть интересная идея, но свободного кэша недостаточно; сначала нужна отдельная проверка."
    elif has_large_hold_not_add:
        final_action = "WAIT"
        recommended_purchase_usd = 0
        main_reason = "Крупные позиции уже занимают значимую долю; наращивать без сильной просадки нельзя."

    if cash_status["cash_left_usd"] <= 0:
        recommended_purchase_usd = 0

    market_quality_score = min(max(round(best_strength / 4), 1), 10) if best_strength else 3

    return {
        "final_action": final_action,
        "recommended_purchase_usd": recommended_purchase_usd,
        "main_reason": main_reason,
        "market_quality_score": market_quality_score,
        "action_probability": action_probability,
        "strong_new_ideas_count": len(new_ideas),
        "new_ideas": new_ideas,
        "cash_status": cash_status,
        "asset_decisions": asset_decisions,
    }


def human_action(action):
    mapping = {
        "WAIT": "⏳ Ждать",
        "BUY_SMALL": "✅ Купить небольшую позицию",
        "SELL": "💰 Продать / сократить",
        "NO_ACTION": "❌ Ничего не делать",
        "HOLD": "Держать",
        "HOLD_NOT_ADD": "Держать, но не наращивать",
        "WATCH": "Наблюдать",
    }
    return mapping.get(action, action)


def format_decisions_for_prompt(decisions):
    if not decisions:
        return "Алгоритм не нашел решений, требующих действий."

    cash = decisions["cash_status"]
    lines = []

    lines.append("📌 РЕШЕНИЕ НА СЕГОДНЯ")
    lines.append(f"Итог: {human_action(decisions['final_action'])}")
    lines.append(f"Рекомендуемая покупка сегодня: {decisions['recommended_purchase_usd']} $")
    lines.append(f"Причина: {decisions['main_reason']}")
    lines.append(f"Качество рынка: {decisions['market_quality_score']}/10")
    lines.append(f"Вероятность действия: {decisions['action_probability']}%")
    lines.append(f"Сильных новых идей: {decisions['strong_new_ideas_count']}")
    lines.append("")

    lines.append("💰 ИНВЕСТИЦИОННЫЙ БЮДЖЕТ")
    lines.append(f"Месяц: {cash['month']}")
    lines.append(f"Минимальный план пополнения: {cash['target_min_usd']} $")
    lines.append(f"Внесено: {cash['deposited_usd']} $")
    lines.append(f"Уже инвестировано: {cash['invested_usd']} $")
    lines.append(f"Свободный кэш: {cash['cash_left_usd']} $")
    lines.append(f"До минимального плана не хватает: {cash['shortfall_usd']} $")
    lines.append("")

    lines.append("📊 РЕШЕНИЯ ПО КЛАССАМ АКТИВОВ")
    for item in decisions["asset_decisions"][:6]:
        weight = item["portfolio_weight"]
        weight_text = "нет точной доли" if weight is None else f"{weight}%"
        lines.append(f"{item['title']}: {human_action(item['action'])}")
        lines.append(f"Доля: {weight_text}; причина: {item['reason']}.")

    lines.append("")
    lines.append("🧭 НОВЫЕ ИДЕИ")
    if decisions["new_ideas"]:
        for idea in decisions["new_ideas"]:
            tickers = ", ".join(idea["tickers"]) if idea["tickers"] else "без тикера"
            lines.append(f"{idea['title']} ({tickers})")
    else:
        lines.append("Сильных новых идей сегодня нет.")

    return "\n".join(lines)
