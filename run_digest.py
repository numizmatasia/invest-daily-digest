import json
import re

import requests

import main

VERSION = "STAGE4-QUALITY-v3.4-STRICT-VERIFICATION"
MAX_REPORT_EVENTS = 2
MAX_DIGEST_CHARS = 3800
STRICT_CONFIRMATION_CODES = {"OFFICIAL_CONFIRMED", "MULTI_SOURCE_CONFIRMED"}


def clean_line(value):
    text = main.clean_text(value)
    replacements = (
        (r"\bбычий рынок\b", "растущий рынок"),
        (r"\bмедвежий рынок\b", "падающий рынок"),
        (r"\bволатильност\w*\b", "сильные колебания цены"),
        (r"\bралли\b", "быстрый рост цен"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(
        r"\bФРС\b(?!\s*\(центральный банк США\))",
        "ФРС (центральный банк США)",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(ФРС \(центральный банк США\))(?:\s*\(центральный банк США\))+",
        r"\1",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def compact(value, limit):
    text = clean_line(value)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"


def broad_macro_event(event):
    if event.get("primary_subject") != "US_MARKET" or event.get("direct_user_relevance"):
        return True
    text = " ".join(a.get("title", "") for a in event.get("articles", [])).lower()
    terms = (
        "federal reserve", "fed ", "inflation", "cpi", "pce",
        "jobs report", "payroll", "unemployment", "gdp",
        "treasury yield", "rate cut", "rate hike", "u.s.-china",
        "us-china", "china-us", "global trade",
    )
    return any(term in text for term in terms)


def select_strict_events(confirmed, research):
    del research
    result = []
    for event in confirmed:
        if event.get("confirmation", {}).get("code") not in STRICT_CONFIRMATION_CODES:
            continue
        if not broad_macro_event(event):
            continue
        event["display_tier"] = "CONFIRMED"
        result.append(event)
    return main.final_deduplicate(result)[:MAX_REPORT_EVENTS]


def fallback_analysis(event, index):
    mappings = {
        "ENERGY": ("XLE", "СМЕШАННО / УМЕРЕННОЕ", "Рост нефти поддерживает нефтяные компании, но может усилить инфляцию и давление на широкий рынок."),
        "URANIUM": ("CCJ, KZAPD, UROY", "НЕЙТРАЛЬНО / СЛАБОЕ", "Для решения нужны числовые данные о добыче, контрактах или цене урана."),
        "SEMICONDUCTORS": ("MU, AMAT, AVGO, SKHY", "НЕЙТРАЛЬНО / СЛАБОЕ", "Для решения нужны данные о прибыли, прогнозе продаж или спросе на микросхемы."),
        "PRECIOUS_METALS": ("SIVR, PSLV", "НЕЙТРАЛЬНО / СЛАБОЕ", "Для решения нужны данные о ставках, долларе и спросе на серебро."),
        "CRYPTO": ("IBIT", "НЕЙТРАЛЬНО / СЛАБОЕ", "Для решения нужны подтверждённые данные о спросе на Bitcoin или регулировании."),
        "US_MARKET": ("SPY, SPYM, QQQM, VT, IXUS", "НЕЙТРАЛЬНО / СЛАБОЕ", "Одного события недостаточно для изменения широкого индексного портфеля."),
    }
    affected, impact, reason = mappings.get(
        event.get("primary_subject"),
        ("прямой связи нет", "НЕЙТРАЛЬНО / СЛАБОЕ", "Доказанного влияния на инвестиционный тезис пока нет."),
    )
    rep = event["representative"]
    return {
        "index": index,
        "title_ru": compact(rep.get("title", ""), 125),
        "what_happened_ru": compact(rep.get("summary") or rep.get("title", ""), 210),
        "impact_label": impact,
        "impact_reason_ru": reason,
        "affected_positions_ru": affected,
        "today_action_ru": "Не менять позиции только из-за этого события.",
        "decision_trigger_ru": "Пересмотреть решение после подтверждённого числового изменения прибыли, прогноза, производства, ставки или цены сырья.",
        "action_code": "HOLD",
    }


def analyze_event(event, index):
    backup = fallback_analysis(event, index)
    if not main.GEMINI_API_KEY:
        return backup, False, "ключ отсутствует"
    payload = {
        "subjects": sorted(event.get("subjects", [])),
        "event_type": event.get("event_type"),
        "confirmation": event.get("confirmation", {}).get("label"),
        "titles": [a.get("title", "") for a in event.get("articles", [])[:4]],
        "summaries": [main.trim_text(a.get("summary", ""), 260) for a in event.get("articles", [])[:3]],
    }
    prompt = f"""
Подготовь короткий блок личного инвестиционного дайджеста на русском языке. Верни только JSON.
Не выдумывай причины, цены, проценты и рекомендации. Переведи английский текст.
Направление: ПОЛОЖИТЕЛЬНО, ОТРИЦАТЕЛЬНО, СМЕШАННО или НЕЙТРАЛЬНО.
Сила: СИЛЬНОЕ, УМЕРЕННОЕ или СЛАБОЕ.
Действие сегодня не может быть «проанализировать», «изучить», «проверить» или «следить».
Без текущих цен разрешено только сохранить позиции без сделки.
Каждое поле не более 180 символов.
Поля: title_ru, what_happened_ru, impact_label, impact_reason_ru, affected_positions_ru, today_action_ru, decision_trigger_ru, action_code.
impact_label строго: «НАПРАВЛЕНИЕ / СИЛА». action_code: HOLD или NO_ACTION.
Событие: {json.dumps(payload, ensure_ascii=False)}
""".strip()
    try:
        response = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/" + f"{main.GEMINI_MODEL}:generateContent?key={main.GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0}},
            timeout=main.GEMINI_TIMEOUT,
        )
        response.raise_for_status()
        result = json.loads(response.json()["candidates"][0]["content"]["parts"][0]["text"])
        required = ("title_ru", "what_happened_ru", "impact_label", "impact_reason_ru", "affected_positions_ru", "today_action_ru", "decision_trigger_ru")
        if any(not clean_line(result.get(field)) for field in required):
            raise ValueError("неполный ответ Gemini")
        action = clean_line(result["today_action_ru"]).lower()
        if any(word in action for word in ("проанализ", "изуч", "след", "провер", "рассмотр")):
            result["today_action_ru"] = "Не менять позиции только из-за этого события."
        result["index"] = index
        result["action_code"] = result.get("action_code") if result.get("action_code") in {"HOLD", "NO_ACTION"} else "HOLD"
        for field in required:
            result[field] = compact(result[field], 190)
        return result, True, "ok"
    except Exception as error:
        return backup, False, str(error)


def portfolio_tickers(portfolio_data):
    text = json.dumps(portfolio_data, ensure_ascii=False).upper()
    return sorted(ticker for ticker in main.ENTITY_ALIASES if re.search(rf"(?<![A-Z0-9]){re.escape(ticker)}(?![A-Z0-9])", text))


def main_decision(events, analyses):
    if not events:
        return (
            "Сегодня портфель не менять: событий с официальным подтверждением или подтверждением двумя независимыми источниками не найдено.",
            "Решение изменится после появления такого подтверждённого события.",
        )
    top_event, top_analysis = max(zip(events, analyses), key=lambda pair: pair[0].get("score", 0))
    del top_event
    return compact(top_analysis["today_action_ru"], 210), compact(top_analysis["decision_trigger_ru"], 230)


def render_digest(events, analyses, portfolio_data):
    action, trigger = main_decision(events, analyses)
    lines = [
        "📊 ЕЖЕДНЕВНЫЙ ИНВЕСТИЦИОННЫЙ ДАЙДЖЕСТ",
        f"Версия: {VERSION}", "", "✅ РЕШЕНИЕ НА СЕГОДНЯ", action,
        "", "Что изменит решение:", trigger,
        "", "🔄 ГЛАВНЫЕ ПОДТВЕРЖДЁННЫЕ СОБЫТИЯ",
    ]
    if not events:
        lines.append("Событий, подтверждённых официальным источником или двумя независимыми надёжными источниками, за период не найдено.")
    for number, (event, analysis) in enumerate(zip(events, analyses), 1):
        lines.extend([
            "", f"{number}. {compact(analysis['title_ru'], 135)}",
            f"Факт: {compact(analysis['what_happened_ru'], 210)}",
            f"Влияние: {compact(analysis['impact_label'], 60)}",
            f"Почему: {compact(analysis['impact_reason_ru'], 190)}",
            f"Позиции: {compact(analysis['affected_positions_ru'], 90)}.",
            f"Действие: {compact(analysis['today_action_ru'], 170)}",
            f"Сигнал: {compact(analysis['decision_trigger_ru'], 190)}",
            f"Проверка: {event['confirmation']['label']}.",
        ])
    held = portfolio_tickers(portfolio_data)
    affected = set()
    for analysis in analyses:
        for ticker in main.ENTITY_ALIASES:
            if ticker in analysis.get("affected_positions_ru", ""):
                affected.add(ticker)
    lines.extend(["", "📌 МОЙ ПОРТФЕЛЬ"])
    if affected & set(held):
        for ticker in sorted(affected & set(held)):
            lines.append(f"• {ticker}: сохранить позицию без сделки.")
    else:
        lines.append("• Подтверждённых оснований менять позиции нет.")
    unchanged = sorted(set(held) - affected)
    if unchanged:
        lines.append("• Без новых существенных сигналов: " + ", ".join(unchanged) + ".")
    lines.extend([
        "", "💰 ЕЖЕМЕСЯЧНОЕ ПОПОЛНЕНИЕ",
        f"Минимальный план {main.MONTHLY_BUDGET_USD} $ сохраняется.",
        "Без текущих цен точка входа и размер сделки не определяются.",
        "", "🔎 НОВЫЕ ВОЗМОЖНОСТИ ВНЕ ПОРТФЕЛЯ",
        "Подтверждённых кандидатов с достаточными данными для сделки сегодня нет.",
        "", "⚠️ Одиночные сообщения СМИ и слухи в основной блок не включаются.",
    ])
    return "\n".join(lines)


def build_digest(events, analyses, portfolio_data, watchlist_data, stats, source_status, processing):
    del watchlist_data, stats, source_status, processing
    digest = render_digest(events, analyses, portfolio_data)
    if len(digest) <= MAX_DIGEST_CHARS:
        return digest
    digest = render_digest(events[:1], analyses[:1], portfolio_data)
    if len(digest) <= MAX_DIGEST_CHARS:
        return digest
    return render_digest([], [], portfolio_data)


def self_tests():
    assert "центральный банк США) (центральный банк США" not in clean_line("ФРС (центральный банк США) (центральный банк США)")
    assert select_strict_events([], []) == []
    assert len(render_digest([], [], {})) < MAX_DIGEST_CHARS
    assert "НОВЫЕ ВОЗМОЖНОСТИ" in render_digest([], [], {})


main.VERSION = VERSION
main.MAX_CONFIRMED_EVENTS = 6
main.MAX_RESEARCH_EVENTS = 0
main.select_events_for_report = select_strict_events
main.analyze_one_event_with_gemini = analyze_event
main.build_digest = build_digest
main.run_self_tests = self_tests

if __name__ == "__main__":
    main.main()
