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
    if data.get("schema_version") != "1.0":
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
        "run_release_gate_or_stop",
        "main",
    ]
    missing_functions = [name for name in required_functions if not callable(getattr(module, name, None))]
    if missing_functions:
        fail("Нет обязательных функций: " + ", ".join(missing_functions))

    if getattr(module, "MONTHLY_BUDGET_USD", None) != 400:
        fail("MONTHLY_BUDGET_USD должен быть равен 400")
    if getattr(module, "RELEASE_GATE_SCHEMA_VERSION", None) != "1.0":
        fail("RELEASE_GATE_SCHEMA_VERSION должен быть 1.0")
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
    if "публикаций 12" not in normal_text or "событий 5" not in normal_text:
        fail("Статистика полноты не показывает количество публикаций и событий")
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
