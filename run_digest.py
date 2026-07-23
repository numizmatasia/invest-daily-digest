import re

import main


PLAIN_LANGUAGE_REPLACEMENTS = (
    (r"\bбычий рынок\b", "растущий рынок (период, когда большинство акций долго растёт)"),
    (r"\bмедвежий рынок\b", "падающий рынок (период, когда большинство акций долго снижается)"),
    (r"\bбычий сигнал\b", "сигнал в пользу роста цены"),
    (r"\bмедвежий сигнал\b", "сигнал в пользу снижения цены"),
    (r"\bФРС\b", "ФРС (центральный банк США)"),
    (
        r"\bФедеральн(?:ая|ой|ую) резервн(?:ая|ой|ую) систем(?:а|ы|у)\b",
        "ФРС (центральный банк США)",
    ),
    (
        r"\bказначейск(?:ие|их|ими|ая|ой|ую) облигаци(?:и|й|ями|я|ю) США\b",
        "государственные облигации США (долг правительства США)",
    ),
    (
        r"\bдоходность облигаций\b",
        "доходность облигаций (сколько инвестор может заработать на них)",
    ),
    (
        r"\bдоходность казначейских облигаций\b",
        "доходность государственных облигаций США (сколько инвестор может заработать на них)",
    ),
    (
        r"\bястребин(?:ая|ой|ую) политик(?:а|и|у)\b",
        "жёсткая политика высоких ставок для борьбы с инфляцией",
    ),
    (
        r"\bголубин(?:ая|ой|ую) политик(?:а|и|у)\b",
        "мягкая политика снижения ставок для поддержки экономики",
    ),
    (r"\bволатильност(?:ь|и|ью)\b", "сильные колебания цены"),
    (
        r"\bфундаментальн(?:ые|ых|ыми) показател(?:и|ей|ями)\b",
        "основные показатели компании: прибыль, выручка, долги и производство",
    ),
    (r"\bкоррекци(?:я|и|ю|ей) рынка\b", "временное снижение рынка после роста"),
    (r"\bралли\b", "быстрый заметный рост цен"),
    (r"\bраспродаж(?:а|и|у|ей)\b", "массовая продажа активов и падение цен"),
    (
        r"\bликвидност(?:ь|и|ью)\b",
        "возможность быстро купить или продать актив без сильного изменения цены",
    ),
)


def plain_language(value):
    text = str(value or "")
    for pattern, replacement in PLAIN_LANGUAGE_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return " ".join(text.split())


def simplify_analysis(analysis):
    if not isinstance(analysis, dict):
        return analysis

    text_fields = (
        "title_ru",
        "what_happened_ru",
        "relevance_ru",
        "impact_reason_ru",
        "watch_ru",
        "action_reason_ru",
        "today_action_ru",
        "decision_trigger_ru",
        "invalidation_ru",
    )
    result = dict(analysis)
    for field in text_fields:
        if field in result:
            result[field] = plain_language(result[field])
    return result


_original_analyze = main.analyze_one_event_with_gemini
_original_build_digest = main.build_digest


def analyze_one_event_with_plain_language(event, index):
    analysis, used_gemini, status = _original_analyze(event, index)
    return simplify_analysis(analysis), used_gemini, status


def build_plain_language_digest(*args, **kwargs):
    digest = _original_build_digest(*args, **kwargs)
    return plain_language(digest)


main.VERSION = "STAGE4-QUALITY-v3.2-PLAIN-LANGUAGE"
main.analyze_one_event_with_gemini = analyze_one_event_with_plain_language
main.build_digest = build_plain_language_digest


if __name__ == "__main__":
    main.main()
