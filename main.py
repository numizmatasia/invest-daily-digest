import os
import json
import feedparser
import requests
from datetime import datetime
from google import genai

from news_processor import process_news, format_news_for_prompt
from event_engine import detect_events, format_events_for_prompt
from decision_engine import make_decisions, format_decisions_for_prompt

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
        result.append(f"{ticker} {name}" if name else ticker)
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

decisions = make_decisions(detected_events, portfolio_data, cash_log)
decisions_text = format_decisions_for_prompt(decisions)

prompt = f"""
Ты мой личный инвестиционный помощник v2.0.

Твоя задача — НЕ принимать решение заново, а коротко оформить уже готовое решение алгоритма.

ЖЕСТКИЕ ПРАВИЛА:
- Начинай ответ строго с блока <b>📌 РЕШЕНИЕ НА СЕГОДНЯ</b>.
- Не пиши приветствия.
- Не пиши "давай посмотрим", "я на связи", "сегодня разберем".
- Не выдумывай факты.
- Не спорь с алгоритмом.
- Не добавляй идеи, которых нет в блоке решений.
- Не показывай внутренние технические числа вроде "важность 15".
- Максимум 2300 символов.
- Сначала решение, потом объяснение.
- Если рекомендованная покупка 0 $, не предлагай купить.
- Если актив уже крупный, пиши: держать, но не наращивать без сильной просадки.

Мои портфели:

{PORTFOLIO_TEXT}

Мой Watch List:

{WATCH_LIST}

Решения алгоритма:

{decisions_text}

Инвестиционные события для проверки фактов:

{events_text}

Полный список новостей за сутки только для проверки фактов:

{raw_news}

ФОРМАТ ОТВЕТА ДЛЯ TELEGRAM.
Используй HTML-теги для жирного текста: <b>текст</b>.

<b>📌 РЕШЕНИЕ НА СЕГОДНЯ</b>
Итог: купить / ждать / продать / ничего не делать.
Сумма покупки сегодня: X $.
Причина: одно короткое предложение.

<b>💰 Инвестиционный бюджет</b>
Минимальный план месяца, внесено, свободный кэш, сколько можно использовать сегодня.

<b>📊 Что делать с портфелем</b>
Пиши по классам активов, а не длинным списком тикеров:
- американские акции;
- уран;
- энергетика;
- ИИ и полупроводники;
- золото/серебро;
- крипто.

<b>🧭 Новые идеи</b>
Только если алгоритм нашел новые идеи. Если нет — напиши: сильных новых идей сегодня нет.

<b>🚫 Что сегодня НЕ делать</b>
До 3 пунктов.

<b>📰 Почему</b>
Максимум 3 коротких пункта по событиям дня.
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
    analysis_result = f"""
<b>📌 РЕШЕНИЕ НА СЕГОДНЯ</b>
Итог: ⏳ Ждать
Сумма покупки сегодня: 0 $
Причина: Gemini временно недоступен, нельзя принимать решения без объяснения.

<b>Технически</b>
Собрано новостей: {len(processed_news)}
Найдено событий: {len(detected_events)}
"""

send_to_telegram(analysis_result)
print(f"Финиш скрипта UTC: {datetime.utcnow()}")
