from datetime import datetime


ASSET_CLASSES = {
    "american_equities": {
        "name": "Американский рынок",
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
                "portfolio": None,
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
                "portfolio": portfolio_name,
                "weight": weight,
            })

    return decisions


def _latest_cash_month(cash_log):
    if not cash_log:
        current = datetime.utcnow().strftime("%Y-%m")
        return current, {"target_min_usd": 400, "deposited_usd": 0, "invested_usd": 0, "cash_left_usd": 0}
    month = sorted(cash_log.keys())[-1]
    return month, cash_log.get(month, {})


def _portfolio_asset_classes(portfolio_name, positions):
    rows = []
    normalized = {ticker.upper(): weight for ticker, weight in positions.items()}

    for class_id, class_data in ASSET_CLASSES.items():
        class_tickers = set(class_data["tickers"])
        held = [ticker for ticker in normalized if ticker in class_tickers]
        if not held:
            continue

        known_weight = 0.0
        unknown = []
        for ticker in held:
            weight = normalized[ticker]
            if weight is None:
                unknown.append(ticker)
            else:
                known_weight += float(weight)

        known_weight = round(known_weight, 2)
        if unknown and known_weight == 0:
            action = "наблюдать"
            note = "размер позиций неизвестен"
        elif known_weight >= 20:
            action = "держать, не увеличивать"
            note = "доля высокая"
        elif known_weight >= 7:
            action = "держать"
            note = "доля заметная"
        else:
            action = "наблюдать"
            note = "сильного сигнала к покупке нет"

        rows.append({
            "portfolio": portfolio_name,
            "class_id": class_id,
            "name": class_data["name"],
            "tickers": sorted(held),
            "weight": known_weight,
            "unknown_tickers": sorted(unknown),
            "action": action,
            "note": note,
        })

    return rows


def _portfolio_sections(portfolio_data, decisions):
    sections = {}
    for portfolio_name, positions in portfolio_data.items():
        attention = []
        for decision in decisions:
            if decision.get("portfolio") != portfolio_name:
                continue
            # Показываем только то, что реально требует внимания. Обычные watch не засоряют отчет.
            if decision.get("action") == "hold_not_add" and decision.get("importance", 0) >= 12:
                ticker = decision.get("tickers", [""])[0]
                attention.append({
                    "ticker": ticker,
                    "action": "держать, не увеличивать",
                    "reason": "доля уже крупная, текущие новости не являются сигналом к докупке",
                })

        unique_attention = []
        seen = set()
        for item in attention:
            if item["ticker"] not in seen:
                seen.add(item["ticker"])
                unique_attention.append(item)

        sections[portfolio_name] = {
            "attention": unique_attention,
            "asset_classes": _portfolio_asset_classes(portfolio_name, positions),
        }
    return sections


def _watchlist_signals(events, watchlist_data):
    items = watchlist_data.get("watchlist", []) if isinstance(watchlist_data, dict) else []
    watch_tickers = {item.get("ticker", "").upper(): item.get("name", "") for item in items}
    if not watch_tickers:
        return []

    signals = []
    for event in events:
        if event.get("importance", 0) < 10:
            continue
        related = [ticker.upper() for ticker in event.get("portfolio_links", [])]
        for ticker in related:
            if ticker in watch_tickers:
                signals.append({
                    "ticker": ticker,
                    "name": watch_tickers[ticker],
                    "action": "наблюдать",
                    "reason": "есть тематический сигнал, но не сигнал к покупке",
                })

    result = []
    seen = set()
    for signal in signals:
        if signal["ticker"] not in seen:
            seen.add(signal["ticker"])
            result.append(signal)
    return result[:3]


def _speculative_ideas(events):
    # Пока не открываем спекулятивные сделки автоматически: RSS дает много шума.
    # Если event_engine найдет scout_events, показываем только как наблюдение.
    ideas = []
    for event in events:
        if event.get("id") == "scout_events" and event.get("importance", 0) >= 12:
            ideas.append({
                "ticker": "не определен",
                "action": "проверить вручную",
                "amount_usd": 0,
                "risk": "высокий",
                "reason": "обнаружено рыночное событие типа IPO/ADR/split/M&A, но без надежного тикера покупку не открывать",
            })
    return ideas[:2]


def build_daily_decision(events, decisions, portfolio_data, cash_log, watchlist_data=None):
    month, cash = _latest_cash_month(cash_log)

    target_min = int(cash.get("target_min_usd", 400) or 400)
    deposited = int(cash.get("deposited_usd", 0) or 0)
    invested = int(cash.get("invested_usd", 0) or 0)
    cash_left = int(cash.get("cash_left_usd", 0) or 0)
    missing = max(target_min - deposited, 0)

    spec_ideas = _speculative_ideas(events)
    real_spec_buy = [idea for idea in spec_ideas if idea.get("amount_usd", 0) > 0]

    if real_spec_buy and cash_left > 0:
        action = "BUY_SPEC"
        action_ru = "✅ Спекулятивная покупка"
        purchase_amount = min(cash_left, real_spec_buy[0]["amount_usd"])
        why = "Есть отдельная спекулятивная идея, но сумма ограничена из-за высокого риска."
    else:
        action = "WAIT"
        action_ru = "⏳ Ждать"
        purchase_amount = 0
        why = "В портфеле уже есть крупные доли, а сильных новых идей для покупки сегодня нет."

    return {
        "action": action,
        "action_ru": action_ru,
        "purchase_amount_usd": purchase_amount,
        "confidence_pct": 88 if purchase_amount == 0 else 76,
        "why": why,
        "budget": {
            "month": month,
            "target_min_usd": target_min,
            "deposited_usd": deposited,
            "invested_usd": invested,
            "cash_left_usd": cash_left,
            "missing_to_target_usd": missing,
        },
        "portfolio_sections": _portfolio_sections(portfolio_data, decisions),
        "watchlist_signals": _watchlist_signals(events, watchlist_data or {}),
        "speculative_ideas": spec_ideas,
        "do_not_do": [
            "Не наращивать крупные позиции без сильной просадки.",
            "Не тратить свободный кэш без сильной идеи.",
            "Не открывать спекулятивные сделки без понятного тикера и ограничения суммы.",
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
    return format_compact_report(daily_decision)


def _format_portfolio_section(portfolio_name, section):
    lines = [f"<b>💼 {portfolio_name}</b>"]

    attention = section.get("attention", [])
    if attention:
        lines.append("⚠️ Требуют внимания:")
        for item in attention[:3]:
            lines.append(f"• {item['ticker']}: {item['action']}.")
            lines.append(f"  Причина: {item['reason']}.")
    else:
        lines.append("✅ Все позиции без срочных действий.")

    class_lines = []
    for row in section.get("asset_classes", [])[:4]:
        if row.get("unknown_tickers") and row.get("weight", 0) == 0:
            class_lines.append(f"• {row['name']}: наблюдать, размер позиций неизвестен.")
        elif row.get("weight", 0) >= 20:
            class_lines.append(f"• {row['name']}: держать, не увеличивать.")
        elif row.get("weight", 0) >= 7:
            class_lines.append(f"• {row['name']}: держать.")
        else:
            class_lines.append(f"• {row['name']}: наблюдать.")

    if class_lines:
        lines.extend(class_lines)

    return "\n".join(lines)


def format_compact_report(daily_decision):
    budget = daily_decision["budget"]

    if daily_decision["purchase_amount_usd"] == 0:
        budget_text = (
            f"Минимальный план месяца: {budget['target_min_usd']} $. "
            "Сегодня пополнять счет не требуется: сильных идей для покупки нет."
        )
    else:
        budget_text = (
            f"Минимальный план месяца: {budget['target_min_usd']} $. "
            f"Сегодня использовать: {daily_decision['purchase_amount_usd']} $."
        )

    lines = [
        "<b>📌 РЕШЕНИЕ НА СЕГОДНЯ</b>",
        daily_decision["action_ru"],
        f"Уверенность алгоритма: {daily_decision['confidence_pct']}%",
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
    ]

    for portfolio_name, section in daily_decision.get("portfolio_sections", {}).items():
        lines.append(_format_portfolio_section(portfolio_name, section))
        lines.append("")

    watchlist = daily_decision.get("watchlist_signals", [])
    lines.append("<b>👀 Watch List</b>")
    if watchlist:
        for item in watchlist:
            name = f" ({item['name']})" if item.get("name") else ""
            lines.append(f"• {item['ticker']}{name}: {item['action']}.")
            lines.append(f"  Причина: {item['reason']}.")
    else:
        lines.append("Важных сигналов по Watch List сегодня нет.")
    lines.append("")

    lines.append("<b>🚀 Спекулятивные идеи</b>")
    spec = daily_decision.get("speculative_ideas", [])
    if spec:
        for item in spec:
            lines.append(f"• Тикер: {item['ticker']}.")
            lines.append(f"  Действие: {item['action']}. Сумма: {item['amount_usd']} $. Риск: {item['risk']}.")
            lines.append(f"  Причина: {item['reason']}.")
    else:
        lines.append("Качественных спекулятивных сделок сегодня нет.")
    lines.append("")

    lines.append("<b>🚫 Сегодня НЕ делать</b>")
    for i, item in enumerate(daily_decision.get("do_not_do", [])[:3], start=1):
        lines.append(f"{i}. {item}")

    lines.extend([
        "",
        "<b>План действий:</b>",
        "Ничего не покупать. Остальные позиции оставить без изменений." if daily_decision['purchase_amount_usd'] == 0 else f"Покупать только в пределах {daily_decision['purchase_amount_usd']} $.",
    ])

    return "\n".join(lines)
