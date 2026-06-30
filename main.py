import os
import json
import feedparser
import requests
from datetime import datetime
from google import genai

from news_processor import process_news, format_news_for_prompt
from event_engine import detect_events, format_events_for_prompt

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

PORTFOLIO_TEXT = format_portfolio(portfolio_data)
WATCH_LIST = format_watchlist(watchlist_data)

raw_news_items = collect_raw_news()
processed_news = process_news(raw_news_items)

raw_news = format_news_for_prompt(processed_news)

event_input = make_event_input(processed_news)
detected_events = detect_events(event_input)
events_text = format_events_for_prompt(detected_events)

prompt = f"""
Ты мой личный инвестиционный помощник v2.0.

Твоя задача — не пересказывать новости, а помочь принять решение:
что важно, что влияет на мои деньги, есть ли возможность заработать, и что делать сегодня.

ЖЕСТКИЕ ПРАВИЛА:
- Начинай ответ строго с блока <b>🎯 ГЛАВНОЕ НА СЕГОДНЯ</b>.
- Не пиши приветствия.
- Не пиши фразы вроде "давай посмотрим", "я на связи", "сегодня разберем".
- Не выдумывай факты.
- Не придумывай идеи без новостей или подтверждений.
- Если сильных идей нет — честно напиши: сегодня ничего делать не нужно.
- Не используй сложные термины без объяснения.
- Не давай рекомендацию только по одной слабой новости.
- Максимум 2500 символов.
- Главный источник анализа — инвестиционные события, найденные алгоритмом.
- Полный список новостей используй только для проверки фактов.
- Учитывай размер позиции в портфеле.
- Если сектор или тикер уже занимает большую долю портфеля, не предлагай докупку без сильной причины.
- Если идея уже есть в портфеле крупной долей, пиши: "держать, но не наращивать без сильной просадки".
- Особенно внимательно к урану: CCJ + UROY + KZAPD уже занимают заметную долю Freedom.
- Не называй подтверждение тренда автоматическим сигналом к покупке.
- Лучше "ждать", чем слабая покупка.

Мои портфели:

{PORTFOLIO_TEXT}

Мой Watch List:

{WATCH_LIST}

Инвестиционные события, найденные алгоритмом:

{events_text}

Полный список новостей за сутки для проверки:

{raw_news}

ПРОВЕРКА ИДЕЙ:
Каждую идею оцени по 7 фильтрам:
1. Что произошло?
2. Это новая информация или рынок уже знал?
3. Влияет ли это на прибыль компании?
4. Цена выглядит разумной или уже перегрета?
5. Как реагирует рынок?
6. Есть ли подтверждение из разных источников?
7. Подходит ли это моим портфелям и риску?

СТАТУС ДНЯ:
Выбери один вариант:
🟢 Спокойный день
🟡 День внимания
🔴 Важный день
⚠️ Экстренный день

ФОРМАТ ОТВЕТА ДЛЯ TELEGRAM.
Используй HTML-теги для жирного текста: <b>текст</b>.

<b>🎯 ГЛАВНОЕ НА СЕГОДНЯ</b>
<b>Одна короткая строка до 20 слов.</b>

<b>Статус дня:</b>
🟢 / 🟡 / 🔴 / ⚠️ + короткая причина.

<b>1️⃣ Что произошло?</b>
Максимум 3 главных события. Не пересказывай все новости подряд.

<b>2️⃣ Что важно сегодня?</b>
События, за которыми нужно следить сегодня. Если нет — напиши: важных событий на сегодня не найдено.

<b>3️⃣ Что влияет на мои деньги?</b>

<b>Freedom:</b>
Только важное для этого портфеля. Если ничего — напиши: существенных изменений нет.

<b>Paidax:</b>
Только важное для этого портфеля. Если ничего — напиши: существенных изменений нет.

<b>4️⃣ Watch List</b>
Пиши только если есть важные изменения по Watch List.

<b>5️⃣ Возможности заработать</b>

<b>🧭 Скаут рынка:</b>
Найди до 2 идей в любых отраслях: IPO, ADR, split, spin-off, резкое движение, отчет, важный контракт.
Если сильных идей нет — прямо напиши: сильных идей для покупки сегодня нет.

<b>👔 Проверка портфельного управляющего:</b>
Объясни, подходит ли идея именно мне:
- долгосрочно
- только для спекуляции
- лучше пропустить

Если идея уже есть у меня крупной долей, обязательно напиши:
"держать, но не наращивать без сильной просадки".

Оцени идеи:
⭐⭐⭐⭐⭐ сильная идея
⭐⭐⭐⭐ хорошая идея, но с условиями
⭐⭐⭐ только наблюдать
⭐⭐ слабая идея
❌ пропустить

<b>6️⃣ Что сегодня НЕ делать</b>
1-3 пункта. Например: не усреднять, не покупать на эмоциях, не продавать без причины.

<b>7️⃣ Итог дня</b>
Выбери только один вариант:
✅ Купить
💰 Продать / зафиксировать прибыль
⏳ Ждать
❌ Ничего не делать

Объясни максимум в 3 предложениях.
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
<b>📈 Личный инвестиционный помощник</b>

Gemini временно недоступен.

Собрано новостей: {len(processed_news)}

Рекомендация:
⏳ Ждать. Не принимать решений без анализа.
"""

send_to_telegram(analysis_result)

print(f"Финиш скрипта UTC: {datetime.utcnow()}")
