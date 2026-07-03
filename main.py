import os
import json
import feedparser
import requests
from datetime import datetime
from google import genai

from news_processor import process_news, format_news_for_prompt
from event_engine import detect_events, format_events_for_prompt
from decision_engine import make_daily_decision, format_daily_decision_for_prompt

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
                        "link": getattr(entry, "link", ""),
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

daily_decision = make_daily_decision(detected_events, portfolio_data, cash_log)
daily_decision_text = format_daily_decision_for_prompt(daily_decision)

prompt = f"""
Ты мой личный инвестиционный помощник v2.0.

Твоя задача — НЕ принимать решение заново, а кратко объяснить решение, которое уже подготовил алгоритм.

ЖЕСТКИЕ ПРАВИЛА:
- Начинай ответ строго с блока <b>📌 РЕШЕНИЕ НА СЕГОДНЯ</b>.
- Не пиши приветствия.
- Не пиши фразы вроде "давай посмотрим", "я на связи", "сегодня разберем".
- Не выдумывай факты.
- Не спорь с решением алгоритма.
- Не показывай внутренние слова вроде BUY_CANDIDATE, WAIT, importance, score.
- Не называй подтверждение тренда сигналом к покупке.
- Если рекомендуемая покупка 0 $, не предлагай купить.
- Если сильных новых идей нет — прямо напиши: сильных новых идей сегодня нет.
- Максимум 2200 символов.
- Пиши простым русским языком.

Мои портфели:

{PORTFOLIO_TEXT}

Мой Watch List:

{WATCH_LIST}

Решение алгоритма:

{daily_decision_text}

Инвестиционные события, найденные алгоритмом:

{events_text}

Полный список новостей за сутки только для проверки фактов:

{raw_news}

ФОРМАТ ОТВЕТА ДЛЯ TELEGRAM.
Используй HTML-теги для жирного текста: <b>текст</b>.

<b>📌 РЕШЕНИЕ НА СЕГОДНЯ</b>
⏳ Ждать / ✅ Купить / 💰 Продать / ❌ Ничего не делать

<b>Сумма покупки сегодня:</b>
0 $ или сумма из решения алгоритма.

<b>Почему:</b>
1-2 коротких предложения.

<b>💰 Инвестиционный бюджет</b>
Минимальный ориентир месяца, внесено, свободный кэш, что делать с пополнением.

<b>📊 Портфель по классам активов</b>
Коротко по классам активов, не перечисляй каждую бумагу без необходимости.

<b>🧭 Новые возможности</b>
Только новые идеи вне портфеля. Если нет — напиши, что сильных новых идей нет.

<b>🚫 Что сегодня НЕ делать</b>
1-3 пункта.

<b>Итог:</b>
Одна короткая финальная фраза.
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
⏳ Ждать

<b>Сумма покупки сегодня:</b>
0 $

<b>Почему:</b>
Gemini временно недоступен. Без финального объяснения не принимаем инвестиционных решений.

<b>Итог:</b>
Ждать и не покупать без анализа.
"""

send_to_telegram(analysis_result)

print(f"Финиш скрипта UTC: {datetime.utcnow()}")
