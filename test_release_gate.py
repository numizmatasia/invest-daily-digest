import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path


class GateFailure(Exception):
    pass


def fail(message):
    raise GateFailure(message)


def load_requirements(base_dir):
    path = base_dir / "PROJECT_REQUIREMENTS.json"
    if not path.exists():
        fail("PROJECT_REQUIREMENTS.json отсутствует")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "1.1":
        fail("Неверная версия схемы требований")
    ids = [item.get("id") for item in data.get("requirements", [])]
    if len(ids) != len(set(ids)) or not ids:
        fail("Требования отсутствуют или содержат дубли ID")
    return data


def import_target(target_path):
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")
    os.environ.setdefault("GEMINI_API_KEY", "")

    # Gate does not fetch RSS. Stub feedparser when it is unavailable locally.
    try:
        import feedparser  # noqa: F401
    except Exception:
        stub = types.ModuleType("feedparser")
        stub.parse = lambda *_args, **_kwargs: None
        sys.modules["feedparser"] = stub

    name = "release_gate_target"
    spec = importlib.util.spec_from_file_location(name, target_path)
    if spec is None or spec.loader is None:
        fail("Не удалось создать import spec для main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_article(module, title, group="REUTERS"):
    profile = {
        "group": group,
        "trust": 98 if group == "REUTERS" else 82,
        "tier": 1 if group == "REUTERS" else 2,
        "kind": "authoritative_media",
        "counts_as_independent": True,
    }
    return {
        "title": title,
        "summary": "",
        "url": "https://example.com/story",
        "domain": "example.com",
        "published_at": datetime.now(timezone.utc),
        "source_name": group,
        "source_profile": profile,
        "subjects": ["SKHY"],
        "primary_subject": "SKHY",
        "event_type": "capital_markets",
        "direct_user_relevance": True,
        "is_opinion": False,
    }


def sample_event(module, tier="CONFIRMED", subject="SKHY", group="REUTERS"):
    article = sample_article(
        module,
        "SK Hynix raises 26.5 billion dollars in U.S. ADR offering",
        group=group,
    )
    article["subjects"] = [subject]
    article["primary_subject"] = subject
    return {
        "primary_subject": subject,
        "subjects": {subject},
        "event_type": "capital_markets",
        "articles": [article],
        "confirmation": {
            "code": "RELIABLE_SINGLE_SOURCE" if tier == "CONFIRMED" else "UNVERIFIED_SINGLE_SOURCE",
            "label": "один надежный источник: REUTERS" if tier == "CONFIRMED" else "один непроверенный источник",
            "independent_count": 1 if tier == "CONFIRMED" else 0,
            "best_trust": 98 if tier == "CONFIRMED" else 62,
        },
        "score": 95 if tier == "CONFIRMED" else 64,
        "newest": datetime.now(timezone.utc),
        "representative": article,
        "display_tier": tier,
    }



def sample_topic_event(module, primary="US_MARKET", event_type="macro"):
    article = sample_article(
        module,
        "Federal Reserve signals a change in interest-rate policy",
        group="REUTERS",
    )
    article["subjects"] = [primary]
    article["primary_subject"] = primary
    article["event_type"] = event_type
    article["direct_user_relevance"] = False
    return {
        "primary_subject": primary,
        "subjects": {primary},
        "event_type": event_type,
        "articles": [article],
        "confirmation": {
            "code": "RELIABLE_SINGLE_SOURCE",
            "label": "один надежный источник: REUTERS",
            "independent_count": 1,
            "best_trust": 98,
        },
        "score": 70,
        "newest": datetime.now(timezone.utc),
        "representative": article,
        "display_tier": "CONFIRMED",
    }



def sample_analysis(subject="SKHY", action="WATCH"):
    return {
        "title_ru": f"Существенное событие по {subject}",
        "what_happened_ru": "Компания сообщила о существенном корпоративном событии.",
        "relevance_ru": f"Событие связано с инструментом {subject} и требует оценки влияния.",
        "impact_label": "Смешанное",
        "impact_reason_ru": "Есть потенциальная поддержка инвестиционного тезиса и одновременно риск волатильности.",
        "watch_ru": "Проверить официальные параметры и реакцию рынка.",
        "action_code": action,
        "action_reason_ru": "Наблюдать до появления котировок и подтвержденных фундаментальных данных.",
    }


def render(module, events, analyses, failures=None, accounts=None, watchlist=None, coverage=None):
    failures = failures or []
    accounts = accounts if accounts is not None else {
        "Freedom": ["SPY", "CCJ"],
        "Paidax": ["MU", "AMAT"],
    }
    watchlist = watchlist if watchlist is not None else ["AVGO", "SKHY"]
    coverage = coverage or {
        "articles_after_quality": 12,
        "clusters_total": 5,
        "confirmed_total": 2,
        "research_total": 1,
        "relevant_total": 3,
    }
    return module.build_report(
        ["feed"] * len(module.BASE_FEEDS),
        ["radar"] * 3,
        failures,
        {
            "filtered_pr": 3,
            "filtered_low_quality": 2,
            "filtered_opinion": 1,
        },
        events,
        analyses,
        "резервный русский шаблон",
        1.5,
        accounts,
        watchlist,
        coverage,
    )


def assert_required_sections(text):
    required = [
        "📋 Что делать сегодня",
        "🔄 Что изменилось",
        "📊 Влияние на мои инвестиции",
        "• Freedom",
        "• Paidax",
        "• Watch List",
        "💰 Инвестиционный бюджет",
        "Минимальный план месяца: 400 $",
        "🔎 Новые возможности",
        "🧭 Полнота данных",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        fail("Отсутствуют обязательные блоки: " + ", ".join(missing))


def run_checks(module, requirements, target_path):
    results = {}

    required_functions = [
        "build_report",
        "overall_action",
        "budget_lines",
        "portfolio_lines",
        "extract_account_positions",
        "extract_watchlist_positions",
        "analyze_events_in_russian",
        "analyze_one_event_with_gemini",
        "same_physical_event",
        "topic_event_is_material",
        "run_release_gate_or_stop",
        "main",
    ]
    missing_functions = [name for name in required_functions if not callable(getattr(module, name, None))]
    if missing_functions:
        fail("Нет обязательных функций: " + ", ".join(missing_functions))

    if getattr(module, "MONTHLY_BUDGET_USD", None) != 400:
        fail("MONTHLY_BUDGET_USD должен быть равен 400")
    if getattr(module, "RELEASE_GATE_SCHEMA_VERSION", None) != "1.1":
        fail("RELEASE_GATE_SCHEMA_VERSION должен быть 1.1")
    if getattr(module, "TELEGRAM_SAFE_LIMIT", 99999) > 3900:
        fail("TELEGRAM_SAFE_LIMIT превышает безопасный предел")

    confirmed = sample_event(module, "CONFIRMED", "SKHY", "REUTERS")
    research = sample_event(module, "RESEARCH", "MU", "MEDIA:unknown")
    normal_text = render(
        module,
        [confirmed, research],
        [sample_analysis("SKHY", "WATCH"), sample_analysis("MU", "RESEARCH")],
    )
    assert_required_sections(normal_text)
    if "🟡 Требует проверки" not in normal_text:
        fail("Непроверенное событие не отделено от подтвержденного")
    if "публикаций 12" not in normal_text or "тематических групп 5" not in normal_text:
        fail("Статистика полноты не показывает количество публикаций и тематических групп")
    if len(normal_text) > module.TELEGRAM_SAFE_LIMIT:
        fail("Обычный отчет превышает лимит Telegram")
    results["R01"] = "PASS"
    results["R02"] = "PASS"
    results["R03"] = "PASS"
    results["R04"] = "PASS"
    results["R05"] = "PASS"
    results["R06"] = "PASS"
    results["R07"] = "PASS"
    results["R08"] = "PASS"
    results["R15"] = "PASS"

    no_events_text = render(
        module,
        [],
        [],
        coverage={
            "articles_after_quality": 7,
            "clusters_total": 0,
            "confirmed_total": 0,
            "research_total": 0,
            "relevant_total": 0,
        },
    )
    assert_required_sections(no_events_text)
    if "ДЕЙСТВИЙ НЕТ" not in no_events_text:
        fail("Ветка без событий не формирует корректное действие")
    results["R10"] = "PASS"

    failure_text = render(
        module,
        [],
        [],
        failures=[{"name": "Reuters", "error": "timeout"}],
    )
    if "❌ Не сработали" not in failure_text or "Reuters" not in failure_text:
        fail("Сбой источника не отражен в отчете")
    results["R09"] = "PASS"

    lower = normal_text.lower()
    forbidden_commands = ["купить сегодня", "продать сегодня", "покупать сейчас", "продавать сейчас"]
    if any(command in lower for command in forbidden_commands):
        fail("Без цен и фундаментальных данных появилась торговая команда")
    if "команд покупать или продавать нет" not in lower:
        fail("Нет явного ограничения торговых команд")
    results["R11"] = "PASS"

    raw_title = confirmed["articles"][0]["title"]
    if raw_title in normal_text:
        fail("Сырой английский заголовок попал в Telegram")
    results["R12"] = "PASS"

    old_key = module.GEMINI_API_KEY
    module.GEMINI_API_KEY = ""
    fallback, status = module.analyze_events_in_russian(
        [confirmed],
        {"SKHY": {"accounts": [], "watchlist": True}},
    )
    module.GEMINI_API_KEY = old_key
    if not fallback or "резерв" not in status.lower():
        fail("При отсутствии Gemini не включился резервный русский режим")
    if not fallback[0].get("title_ru"):
        fail("Резервный режим не сформировал русский разбор")
    results["R13"] = "PASS"

    nested_portfolio = {
        "Freedom": {
            "positions": {
                "SPY": {"weight": 10},
                "CCJ": {"weight": 15},
            }
        },
        "Paidax": [
            {"ticker": "MU", "value": 100},
            {"ticker": "AMAT", "value": 100},
        ],
    }
    parsed = module.extract_account_positions(nested_portfolio)
    if set(parsed.get("Freedom", [])) != {"SPY", "CCJ"}:
        fail("Freedom не распознан во вложенном формате")
    if set(parsed.get("Paidax", [])) != {"MU", "AMAT"}:
        fail("Paidax не распознан во вложенном формате")
    results["R14"] = "PASS"

    sent = []
    originals = {}
    patch_names = [
        "load_json_file", "collect_sources", "deduplicate_articles",
        "quality_filter_articles", "cluster_articles", "classify_event_buckets",
        "select_events_for_report", "analyze_events_in_russian", "send_to_telegram",
    ]
    for name in patch_names:
        originals[name] = getattr(module, name)

    def fake_load(filename):
        if filename == "portfolio.json":
            return nested_portfolio
        return {"watchlist": [{"ticker": "SKHY"}, {"ticker": "AVGO"}]}

    try:
        module.load_json_file = fake_load
        module.collect_sources = lambda _entities: (
            [], ["base"] * len(module.BASE_FEEDS), ["radar"] * 3, [],
            {"filtered_pr": 0, "filtered_low_quality": 0, "filtered_opinion": 0},
        )
        module.deduplicate_articles = lambda articles: articles
        module.quality_filter_articles = lambda articles: (
            articles,
            {"filtered_low_quality": 0, "filtered_opinion": 0},
        )
        module.cluster_articles = lambda _articles, _entities: [confirmed]
        module.classify_event_buckets = lambda _clusters: ([confirmed], [])
        module.select_events_for_report = lambda confirmed_events, research_events: confirmed_events + research_events
        module.analyze_events_in_russian = lambda _events, _locations: ([sample_analysis("SKHY", "WATCH")], "mock Gemini")
        module.send_to_telegram = lambda text: sent.append(text)
        module.main()
    finally:
        for name, value in originals.items():
            setattr(module, name, value)

    if len(sent) != 1:
        fail("Полный main должен отправить ровно одно сообщение")
    assert_required_sections(sent[0])
    results["R16"] = "PASS"

    source_text = Path(target_path).read_text(encoding="utf-8")
    if "run_release_gate_or_stop()" not in source_text:
        fail("main.py не вызывает release gate перед запуском")
    if "test_release_gate.py" not in source_text or "PROJECT_REQUIREMENTS.json" not in source_text:
        fail("main.py не проверяет наличие файлов release gate")
    results["R17"] = "PASS"

    if re_search_import(source_text, "event_engine") or re_search_import(source_text, "decision_engine"):
        fail("Временный контур не должен импортировать event_engine/decision_engine до завершения этапов")
    results["R18"] = "PASS"


    # R19: a broad market event shown in the report must affect the mapped ETFs.
    market_event = sample_topic_event(module)
    market_analysis = sample_analysis("US_MARKET", "WATCH")
    market_text = render(
        module,
        [market_event],
        [market_analysis],
        accounts={
            "Freedom": ["SPY", "VT"],
            "Paidax": ["MU"],
        },
        watchlist=["SKHY"],
        coverage={
            "articles_after_quality": 4,
            "clusters_total": 1,
            "confirmed_total": 1,
            "research_total": 0,
            "relevant_total": 1,
        },
    )
    freedom_block = market_text.split("• Freedom", 1)[1].split("• Paidax", 1)[0]
    if "SPY:" not in freedom_block or "VT:" not in freedom_block:
        fail("Событие US_MARKET не связано с широкими позициями Freedom")
    results["R19"] = "PASS"

    # R20: one malformed Gemini result must not collapse all event analyses.
    partial_events = [
        sample_event(module, "CONFIRMED", "SKHY", "REUTERS"),
        sample_event(module, "CONFIRMED", "MU", "REUTERS"),
        sample_event(module, "RESEARCH", "AMAT", "MEDIA:unknown"),
    ]
    original_key = module.GEMINI_API_KEY
    original_worker = module.analyze_one_event_with_gemini
    module.GEMINI_API_KEY = "test-key"

    def fake_worker(event, locations, index):
        if index == 1:
            return (
                module.fallback_analysis(event, locations, index),
                False,
                "malformed JSON",
            )
        return sample_analysis(event["primary_subject"], "WATCH"), True, "ok"

    try:
        module.analyze_one_event_with_gemini = fake_worker
        partial_results, partial_status = module.analyze_events_in_russian(
            partial_events,
            {
                "SKHY": {"accounts": [], "watchlist": True},
                "MU": {"accounts": ["Paidax"], "watchlist": False},
                "AMAT": {"accounts": ["Paidax"], "watchlist": False},
            },
        )
    finally:
        module.analyze_one_event_with_gemini = original_worker
        module.GEMINI_API_KEY = original_key

    if len(partial_results) != 3:
        fail("Сбой одного ответа Gemini потерял другие события")
    if "успешно 2/3" not in partial_status or "резерв 1/3" not in partial_status:
        fail("Статус Gemini не показывает частичный успех и резерв")
    results["R20"] = "PASS"

    # R21: every selected event must be listed in the Telegram text.
    many_events = []
    many_analyses = []
    subjects = ["SKHY", "MU", "AMAT", "AVGO", "CCJ", "IBIT"]
    for idx, subject in enumerate(subjects):
        tier = "CONFIRMED" if idx < 3 else "RESEARCH"
        event = sample_event(
            module,
            tier,
            subject,
            "REUTERS" if tier == "CONFIRMED" else "MEDIA:unknown",
        )
        event["event_type"] = "capital_markets"
        many_events.append(event)
        analysis = sample_analysis(
            subject,
            "WATCH" if tier == "CONFIRMED" else "RESEARCH",
        )
        analysis["title_ru"] = f"Событие номер {idx + 1} по {subject}"
        many_analyses.append(analysis)

    many_text = render(
        module,
        many_events,
        many_analyses,
        coverage={
            "articles_after_quality": 20,
            "clusters_total": 12,
            "confirmed_total": 3,
            "research_total": 3,
            "relevant_total": 6,
        },
    )
    for analysis in many_analyses:
        if analysis["title_ru"] not in many_text:
            fail("Отобранное событие исчезло из Telegram: " + analysis["title_ru"])
    if "Еще отобрано событий" in many_text:
        fail("Использована запрещенная формулировка о скрытых событиях")
    if "6/6 релевантных событий" not in many_text:
        fail("Отчет не подтверждает, сколько релевантных событий перечислено")
    results["R21"] = "PASS"

    # R22: unrelated same-day strong events must not be merged only by type.
    unrelated_articles = [
        {
            "title": "SK Hynix prices ADR offering at 149 dollars",
            "summary": "",
            "url": "https://reuters.com/a",
            "domain": "reuters.com",
            "published_at": datetime.now(timezone.utc),
            "source_name": "Reuters",
        },
        {
            "title": "SK Hynix appoints banks for a future bond sale",
            "summary": "",
            "url": "https://reuters.com/b",
            "domain": "reuters.com",
            "published_at": datetime.now(timezone.utc),
            "source_name": "Reuters",
        },
    ]
    clusters = module.cluster_articles(
        unrelated_articles,
        {"SKHY": ["SK Hynix", "SK hynix"]},
    )
    if len(clusters) != 2:
        fail("Разные события SKHY ошибочно объединены в один кластер")
    results["R22"] = "PASS"

    # R23: generic broad-market earnings headlines are not material macro events.
    generic_article = sample_article(
        module,
        "Nasdaq earnings preview for the coming week",
        group="REUTERS",
    )
    generic_article.update(
        {
            "subjects": ["US_MARKET"],
            "primary_subject": "US_MARKET",
            "event_type": "earnings",
            "direct_user_relevance": False,
        }
    )
    generic_cluster = {
        "primary_subject": "US_MARKET",
        "subjects": {"US_MARKET"},
        "event_type": "earnings",
        "articles": [generic_article],
        "direct_user_relevance": False,
        "day": datetime.now(timezone.utc).date().isoformat(),
        "seed_title": generic_article["title"],
    }
    confirmed_generic, research_generic = module.classify_event_buckets(
        [generic_cluster]
    )
    if confirmed_generic or research_generic:
        fail("Общий заголовок об отчетности ошибочно признан рыночным событием")
    results["R23"] = "PASS"

    # R24: coverage uses physical/relevant terminology consistently.
    if "тематических групп" not in many_text:
        fail("Статистика не различает публикации и тематические группы")
    results["R24"] = "PASS"

    # R25: malformed JSON on the first Gemini attempt is retried once.
    retry_event = sample_event(module, "CONFIRMED", "SKHY", "REUTERS")
    old_post = module.requests.post
    old_key = module.GEMINI_API_KEY
    module.GEMINI_API_KEY = "test-key"
    calls = []

    class FakeResponse:
        def __init__(self, text):
            self._text = text
        def raise_for_status(self):
            return None
        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": self._text}]
                        }
                    }
                ]
            }

    valid_payload = {
        "title_ru": "Размещение ADR компании SK Hynix",
        "what_happened_ru": "Компания провела крупное размещение депозитарных расписок.",
        "relevance_ru": "SKHY находится в списке наблюдения пользователя.",
        "impact_label": "Смешанное",
        "impact_reason_ru": "Приток капитала поддерживает развитие, но дебют может быть волатильным.",
        "watch_ru": "Проверить цену открытия и условия размещения.",
        "action_code": "WATCH",
        "action_reason_ru": "Наблюдать за первыми торгами и не делать вывод по одному движению.",
    }

    def fake_post(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return FakeResponse('{"title_ru":"оборвано')
        return FakeResponse(json.dumps(valid_payload, ensure_ascii=False))

    try:
        module.requests.post = fake_post
        retry_analysis, retry_success, _detail = module.analyze_one_event_with_gemini(
            retry_event,
            {"SKHY": {"accounts": [], "watchlist": True}},
            0,
        )
    finally:
        module.requests.post = old_post
        module.GEMINI_API_KEY = old_key

    if not retry_success or len(calls) != 2:
        fail("Повтор Gemini после оборванного JSON не сработал")
    if retry_analysis["title_ru"] != valid_payload["title_ru"]:
        fail("После повтора Gemini не принят корректный русский ответ")
    results["R25"] = "PASS"

    # R26: selection must no longer stop at only 2 confirmed + 1 research.
    confirmed_many = [
        sample_event(module, "CONFIRMED", f"SKHY", "REUTERS")
        for _ in range(6)
    ]
    research_many = [
        sample_event(module, "RESEARCH", f"MU", "MEDIA:unknown")
        for _ in range(6)
    ]
    selected_many = module.select_events_for_report(
        confirmed_many,
        research_many,
    )
    if len(selected_many) != 8:
        fail("Лимит отбора снова скрывает почти все релевантные события")
    results["R26"] = "PASS"


    requirement_ids = {item["id"] for item in requirements["requirements"] if item.get("blocking")}
    missing_results = sorted(requirement_ids - set(results))
    if missing_results:
        fail("Нет проверки для требований: " + ", ".join(missing_results))

    return results


def re_search_import(source_text, module_name):
    import re
    return bool(re.search(rf"(^|\n)\s*(from\s+{re.escape(module_name)}\s+import|import\s+{re.escape(module_name)})(\s|$)", source_text))


def main():
    target = Path(os.environ.get("RELEASE_GATE_TARGET", "main.py")).resolve()
    base_dir = target.parent
    if not target.exists():
        print(f"RELEASE GATE: FAIL — target not found: {target}")
        return 1

    try:
        requirements = load_requirements(base_dir)
        module = import_target(target)
        results = run_checks(module, requirements, target)
    except Exception as error:
        print(f"RELEASE GATE: FAIL — {error}")
        return 1

    print("RELEASE GATE: PASS")
    for item in requirements["requirements"]:
        print(f"{item['id']} PASS — {item['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
