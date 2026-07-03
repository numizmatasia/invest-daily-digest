import os
import json
import feedparser
import requests
from datetime import datetime
from google import genai

from news_processor import process_news, format_news_for_prompt
from event_engine import detect_events, format_events_for_prompt
from decision_engine import (
    make_decisions,
    format_decisions_for_prompt,
    build_daily_decision,
    format_daily_decision_for_prompt,
    format_compact_report,
)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

client = genai.Client(api_key=GEMINI_API_KEY)

feeds = [
    "https://world-nuclear-news.org/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://seekingalpha.com/feed.xml",
    "https://www.investing.com/rss/news.rss",
    "https://oilprice.com/rss/main",
    "https://techcrunch.com/feed/",
    "https://www.marketwatch.com/rss/topstories",
    "https://www.prnewswire.com/rss/news-releases-list.rss",
    "https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies",
]

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def load_json_file(filename):
    try:
        with open(filename, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as e:
        print(f"Ошибка чтения файла {filename}: {e}")
        return {}


def format_portfolio(portfolio_data):
    result = []

    for portfolio_name, positions in portfolio_data.items():
        result.append(f"{portfolio_name}:")

        for ticker, weight in positions.items():
            if weight is None:
                result.append(f"{ticker}")
            else:
                result.append(f"{ticker} {weight}%")

        result.append("")

    return "\n".join(result)


def format_watchlist(watchlist_data):
    result = []

    for item in watchlist_data.get("watchlist", []):
        ticker = item.get("ticker", "")
        name = item.get("name", "")

        if name:
            result.append(f"{ticker} {name}")
        else:
            result.append(ticker)

    return "\n".join(result)


def collect_raw_news():
    raw_items = []

    for feed_url in feeds:
        try:
            resp = requests.get(feed_url, headers=headers, timeout=15)
            feed = feedparser.parse(resp.content)

            if feed.entries:
                for entry in feed.entries[:4]:
                    raw_items.append({
                        "source": feed_url,
                        "title": getattr(entry, "title", ""),
                        "summary": getattr(entry, "summary", ""),
                        "link": getattr(entry, "link", "")
                    })
            else:
                print(f"Предупреждение: лента пуста: {feed_url}")

        except Exception as e:
            print(f"Ошибка при чтении {feed_url}: {e}")

    return raw_items


def make_event_input(news_items):
    result = []

    for item in news_items:
        result.append(
            f"Источник: {item.get('source', '')}\n"
            f"Заголовок: {item.get('title', '')}\n"
            f"Описание: {item.get('summary', '')}\n"
            f"Ссылка: {item.get('link', '')}"
        )

    return result


def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    if len(text) > 3900:
        text = text[:3900] + "\n\n...сообщение сокращено из-за лимита Telegram."

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        res = requests.post(url, json=payload, timeout=15)
        res.raise_for_status()
        print("Анализ успешно отправлен в Telegram!")
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")
        if "res" in locals():
            print(f"Ответ Telegram: {res.text}")
        raise e


print(f"Старт скрипта UTC: {datetime.utcnow()}")

portfolio_data = load_json_file("portfolio.json")
watchlist_data = load_json_file("watchlist.json")
cash_log = load_json_file("cash_log.json")

PORTFOLIO_TEXT = format_portfolio(portfolio_data)
WATCH_LIST = format_watchlist(watchlist_data)

raw_news_items = collect_raw_news()
processed_news = process_news(raw_news_items)
raw_news = format_news_for_prompt(processed_news)

event_input = make_event_input(processed_news)
detected_events = detect_events(event_input)
events_text = format_events_for_prompt(detected_events)

decisions = make_decisions(detected_events, portfolio_data)
decisions_text = format_decisions_for_prompt(decisions)

daily_decision = build_daily_decision(detected_events, decisions, portfolio_data, cash_log, watchlist_data)
daily_decision_text = format_daily_decision_for_prompt(daily_decision)
compact_report = format_compact_report(daily_decision)

prompt = f"""
Ты мой личный инвестиционный помощник v2.0.

Твоя задача — аккуратно оформить уже готовое решение алгоритма для Telegram.

ЖЕСТКИЕ ПРАВИЛА:
- Не меняй действие алгоритма.
- Не меняй сумму покупки.
- Не добавляй новые идеи от себя.
- Не пиши приветствия.
- Не используй фразу "покупки акций". Пиши "покупки активов".
- Не упоминай внутренние баллы, action/watch/hold и технические детали.
- Максимум 1500 символов.
- Начинай строго с <b>📌 РЕШЕНИЕ НА СЕГОДНЯ</b>.
- Сохрани структуру готового текста.

ГОТОВЫЙ ТЕКСТ АЛГОРИТМА:

{compact_report}

ДОПОЛНИТЕЛЬНЫЕ ФАКТЫ ДЛЯ ПРОВЕРКИ, НЕ ДЛЯ ПЕРЕСКАЗА:

{events_text}
"""

try:
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        analysis_result = response.text

    except Exception as e:
        print(f"Ошибка Gemini 2.5 Flash: {e}")
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        analysis_result = response.text

except Exception as e:
    print(f"Ошибка Gemini: {e}")

    budget = daily_decision["budget"]
    analysis_result = f"""
<b>📌 РЕШЕНИЕ НА СЕГОДНЯ</b>
{daily_decision['action_ru']}

<b>Сумма покупки сегодня:</b>
{daily_decision['purchase_amount_usd']} $

<b>Почему:</b>
{daily_decision['why']}

<b>💰 Инвестиционный бюджет</b>
Минимальный ориентир: {budget['target_min_usd']} $. Внесено: {budget['deposited_usd']} $. До ориентира не хватает: {budget['missing_to_target_usd']} $.

<b>Итог:</b>
Ждать и не принимать решений без анализа.
"""

analysis_result = analysis_result.replace("покупки акций", "покупки активов")
analysis_result = analysis_result.replace("покупать акции", "покупать активы")

if "<b>📌 РЕШЕНИЕ НА СЕГОДНЯ</b>" not in analysis_result:
    analysis_result = compact_report

send_to_telegram(analysis_result)

print(f"Финиш скрипта UTC: {datetime.utcnow()}")
