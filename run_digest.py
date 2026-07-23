import json
import re

import requests

import main


VERSION = "STAGE4-QUALITY-v3.3-DECISION-FIRST"
MAX_REPORT_EVENTS = 3
MAX_DIGEST_CHARS = 3400


PLAIN_LANGUAGE_REPLACEMENTS = (
    (r"\bбычий рынок\b", "растущий рынок"),
    (r"\bмедвежий рынок\b", "падающий рынок"),
    (r"\bбычий сигнал\b", "сигнал в пользу роста цены"),
    (r"\bмедвежий сигнал\b", "сигнал в пользу снижения цены"),
    (r"\bФРС\b", "ФРС (центральный банк США)"),
    (r"\bказначейск\w* облигаци\w* США\b", "государственные облигации США"),
    (
        r"\bдоходност\w* облигаци\w*\b",
        "доходность облигаций (сколько инвестор получает от облигаций)",
    ),
    (r"\bволатильност\w*\b", "сильные колебания цены"),
    (
        r"\bфундаментальн\w* показател\w*\b",
        "прибыль, выручка, долги и производство компании",
    ),
    (r"\bкоррекци\w* рынка\b", "временное снижение рынка после роста"),
    (r"\bралли\b", "быстрый рост цен"),
    (r"\bликвидност\w*\b", "возможность быстро купить или продать актив"),
)


TOPIC_EFFECTS = {
    "SEMICONDUCTORS": (
        "MU, AMAT, AVGO, SKHY",
        "зависит от прибыли, прогноза продаж и спроса на микросхемы",
    ),
    "ENERGY": (
        "XLE",
        "рост цен на нефть обычно поддерживает нефтяные компании, падение — давит на них",
    ),
    "URANIUM": (
        "CCJ, KZAPD, UROY",
        "важны производство, остановки рудников, контракты и цена урана",
    ),
    "PRECIOUS_METALS": (
        "SIVR, PSLV",
        "важны доллар США, ставки и спрос на защитные активы",
    ),
    "CRYPTO": (
        "IBIT",
        "важны спрос на Bitcoin, доступность денег и отношение инвесторов к риску",
    ),
    "US_MARKET": (
        "SPY, SPYM, QQQM, VT, IXUS",
        "высокие ставки обычно сильнее давят на дорогие акции роста",
    ),
}


def clean_line(value):
    text = main.clean_text(value)
    for pattern, replacement in PLAIN_LANGUAGE_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text.strip()


def compact(value, limit):
    text = clean_line(value)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def confirmed_only(confirmed, research):
    del research
    selected = main.final_deduplicate(confirmed[:MAX_REPORT_EVENTS])
    for event in selected:
        event["display_tier"] = "CONFIRMED"
    return selected


def fallback_plain_analysis(event, index):
    subject = event.get("primary_subject", "GENERAL")
    direct = sorted(s for s in event.get("subjects", []) if s in main.ENTITY_ALIASES)
    affected, explanation = TOPIC_EFFECTS.get(
        subject,
        (", ".join(direct) or "портфель", "доказанного влияния на портфель пока нет"),
    )
    source_title = compact(event["representative"].get("title", ""), 170)
    return {
        "index": index,
        "title_ru": f"{affected}: подтверждённое событие",
        "what_happened_ru": f"Источник сообщил: {source_title}",
        "impact_label": "НЕЙТРАЛЬНО / НЕДОСТАТОЧНО ДАННЫХ",
        "impact_reason_ru": explanation,
        "today_action_ru": "Не менять позиции только из-за этой новости.",
        "decision_trigger_ru": (
            "Пересмотреть решение после нового подтверждённого числового факта: "
            "изменения прибыли, прогноза, производства, ставки или цены сырья."
        ),
        "invalidation_ru": "Не учитывать новость, если последующие данные не меняют инвестиционный тезис.",
        "action_code": "HOLD",
    }


def analyze_event(event, index):
    backup = fallback_plain_analysis(event, index)
    if not main.GEMINI_API_KEY:
        return backup, False, "ключ отсутствует"

    payload = {
        "subject": sorted(event.get("subjects", [])),
        "event_type": event.get("event_type"),
        "confirmation": event["confirmation"]["label"],
        "titles": [a.get("title", "") for a in event.get("articles", [])[:4]],
        "summaries": [main.trim_text(a.get("summary", ""), 350) for a in event.get("articles", [])[:3]],
        "portfolio_relation": main.relation_text(event),
    }

    prompt = f"""
Ты готовишь личный инвестиционный дайджест для начинающего инвестора.

Верни только JSON на русском языке.
Все английские заголовки и факты переведи на русский.
Не повторяй исходный английский текст.
Не используй профессиональный термин без краткого объяснения простыми словами.
Не выдумывай цены, проценты, даты, причины движения или рекомендации.

Нужно отделить факт от предположения и указать:
1. что подтверждено;
2. какие позиции затронуты;
3. направление влияния: ПОЛОЖИТЕЛЬНО, ОТРИЦАТЕЛЬНО, СМЕШАННО или НЕЙТРАЛЬНО;
4. силу влияния: СИЛЬНОЕ, УМЕРЕННОЕ или СЛАБОЕ;
5. что делать сегодня;
6. какой конкретный новый факт изменит решение.

Без текущих цен нельзя рекомендовать немедленную покупку или продажу.
Не пиши общие фразы вроде «следить за ситуацией».
Формулируй коротко.

Поля JSON:
title_ru,
what_happened_ru,
impact_label,
impact_reason_ru,
today_action_ru,
decision_trigger_ru,
invalidation_ru,
action_code.

action_code: HOLD, WATCH или NO_ACTION.

Событие:
{json.dumps(payload, ensure_ascii=False)}
""".strip()

    try:
        response = requests.post(
            (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{main.GEMINI_MODEL}:generateContent?key={main.GEMINI_API_KEY}"
            ),
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.05,
                },
            },
            timeout=main.GEMINI_TIMEOUT,
        )
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(text)

        required = (
            "title_ru",
            "what_happened_ru",
            "impact_label",
            "impact_reason_ru",
            "today_action_ru",
            "decision_trigger_ru",
            "invalidation_ru",
        )
        if any(not clean_line(result.get(field)) for field in required):
            raise ValueError("неполный ответ Gemini")

        result["index"] = index
        result["action_code"] = (
            result.get("action_code")
            if result.get("action_code") in {"HOLD", "WATCH", "NO_ACTION"}
            else "HOLD"
        )
        for field in required:
            result[field] = clean_line(result[field])
        return result, True, "ok"
    except Exception as error:
        return backup, False, str(error)


def choose_decision(events, analyses):
    if not events or not analyses:
        return {
            "today_action_ru": (
                "Сегодня портфель не менять. Подтверждённых событий, "
                "которые требуют сделки, не найдено."
            ),
            "decision_trigger_ru": (
                "Решение изменится после подтверждённого события, "
                "которое меняет прибыль, прогноз, производство, ставки или цену сырья."
            ),
        }

    pairs = list(zip(events, analyses))
    event, analysis = max(
        pairs,
        key=lambda pair: (
            pair[0].get("score", 0),
            pair[0].get("newest"),
        ),
    )
    return analysis


def affected_tickers(event):
    direct = sorted(s for s in event.get("subjects", []) if s in main.ENTITY_ALIASES)
    if direct:
        return direct
    return sorted(main.TOPIC_TICKER_MAP.get(event.get("primary_subject"), []))


def build_digest(
    events,
    analyses,
    portfolio_data,
    watchlist_data,
    stats,
    source_status,
    processing,
):
    del watchlist_data, stats, source_status, processing

    decision = choose_decision(events, analyses)
    lines = [
        "📊 ЕЖЕДНЕВНЫЙ ИНВЕСТИЦИОННЫЙ ДАЙДЖЕСТ",
        f"Версия: {VERSION}",
        "",
        "✅ РЕШЕНИЕ НА СЕГОДНЯ",
        compact(decision["today_action_ru"], 300),
        "",
        "Что изменит решение:",
        compact(decision["decision_trigger_ru"], 320),
        "",
        "🔄 ГЛАВНЫЕ ПОДТВЕРЖДЁННЫЕ СОБЫТИЯ",
    ]

    if not events:
        lines.append("Существенных подтверждённых событий за период не найдено.")

    for number, (event, analysis) in enumerate(zip(events, analyses), 1):
        tickers = ", ".join(affected_tickers(event)) or "прямой связи нет"
        lines.extend(
            [
                "",
                f"{number}. {compact(analysis['title_ru'], 150)}",
                f"Факт: {compact(analysis['what_happened_ru'], 260)}",
                f"Влияние: {compact(analysis['impact_label'], 80)}",
                f"Почему: {compact(analysis['impact_reason_ru'], 240)}",
                f"Позиции: {tickers}.",
                f"Действие: {compact(analysis['today_action_ru'], 210)}",
                f"Сигнал для пересмотра: {compact(analysis['decision_trigger_ru'], 230)}",
                f"Проверка: {event['confirmation']['label']}.",
            ]
        )

    action_map = {}
    for event, analysis in zip(events, analyses):
        for ticker in affected_tickers(event):
            action_map.setdefault(ticker, analysis)

    held = []
    for tickers in main.extract_account_positions(portfolio_data).values():
        held.extend(tickers)
    held = sorted(set(held))

    impacted = [ticker for ticker in held if ticker in action_map]
    lines.extend(["", "📌 МОЙ ПОРТФЕЛЬ"])
    if impacted:
        for ticker in impacted[:6]:
            item = action_map[ticker]
            lines.append(
                f"• {ticker}: {compact(item['impact_label'], 60)} — "
                f"{compact(item['today_action_ru'], 150)}"
            )
    else:
        lines.append("• Нет подтверждённых оснований менять имеющиеся позиции.")

    unchanged = [ticker for ticker in held if ticker not in action_map]
    if unchanged:
        lines.append("• Без существенных изменений: " + ", ".join(unchanged) + ".")

    lines.extend(
        [
            "",
            "💰 ЕЖЕМЕСЯЧНОЕ ПОПОЛНЕНИЕ",
            (
                f"План минимум {main.MONTHLY_BUDGET_USD} $ сохраняется. "
                "Без текущих цен бот не выбирает точку входа; деньги не направлять "
                "в актив только из-за одной новости."
            ),
            "",
            "🔎 НОВЫЕ ВОЗМОЖНОСТИ ВНЕ ПОРТФЕЛЯ",
            "Подтверждённых кандидатов с достаточными данными для решения сегодня нет.",
            "",
            "⚠️ Дайджест использует только подтверждённые события. "
            "Слухи и одиночные непроверенные сообщения исключены.",
        ]
    )

    digest = "\n".join(lines)
    if len(digest) > MAX_DIGEST_CHARS:
        digest = digest[: MAX_DIGEST_CHARS - 60].rsplit("\n", 1)[0]
        digest += "\n\n⚠️ Второстепенные детали сокращены."
    return digest


def self_tests():
    sample = "Строка 1\n\nСтрока 2"
    assert "\n\n" in sample
    assert choose_decision([], [])["today_action_ru"].startswith("Сегодня")
    assert len(build_digest([], [], {}, {}, {}, {}, {})) < MAX_DIGEST_CHARS


main.VERSION = VERSION
main.MAX_CONFIRMED_EVENTS = MAX_REPORT_EVENTS
main.MAX_RESEARCH_EVENTS = 0
main.select_events_for_report = confirmed_only
main.analyze_one_event_with_gemini = analyze_event
main.choose_main_decision = lambda analyses: choose_decision([], analyses)
main.build_digest = build_digest
main.run_self_tests = self_tests


if __name__ == "__main__":
    main.main()
