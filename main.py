import os
import feedparser
import requests
from datetime import datetime
from google import genai

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

FREEDOM_PORTFOLIO = """
SPY 6.87%
VT 5.32%
QQQM 0.92%
IXUS 8.56%
SPYM 17.52%
KZAPD 2.28%
CCJ 17.40%
CORE 0.31%
XLE 6.80%
UROY 5.13%
IBIT 1.44%
SIVR 16.59%
PSLV 10.71%
"""

PAIDAX_PORTFOLIO = """
VT
AMAT
VRT
NVDA
GLD
MU
SPYG
PL
"""

WATCH_LIST = """
AVGO Broadcom
AMZN Amazon
GOOGL Alphabet
SKHY / SK Hynix
META Meta
"""

EVENT_KEYWORDS = [
    "IPO", "initial public offering", "ADR", "Nasdaq listing", "NYSE listing",
    "direct listing", "secondary offering", "share offering", "stock split",
    "spin-off", "spinoff", "index inclusion", "S&P 500", "Nasdaq 100",
    "lock-up", "merger", "acquisition", "listing"
]

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

news = []

print(f"Старт скрипта UTC: {datetime.utcnow()}")

for feed_url in feeds:
    try:
        resp = requests.get(feed_url, headers=headers, timeout=15)
        feed = feedparser.parse(resp.content)

        if feed.entries:
            for entry in feed.entries[:4]:
                title = getattr(entry, "title", "")
                summary = getattr(entry, "summary", "")
                link = getattr(entry, "link", "")

                news.append(
                    f"Источник: {feed_url}\n"
                    f"Заголовок: {title}\n"
                    f"Описание: {summary}\n"
                    f"Ссылка: {link}"
                )
        else:
            print(f"Предупреждение: лента пуста: {feed_url}")

    except Exception as e:
        print(f"Ошибка при чтении {feed_url}: {e}")

raw_news = "\n\n".join(news)

if not raw_news:
    raw_news = "Нет свежих новостей от источников за текущий период."

prompt = f"""
Ты мой личный инвестиционный помощник v2.0.

Твоя задача — не пересказывать новости, а помочь принять решение:
что важно, что влияет на мои деньги, есть ли возможность заработать, и что делать сегодня.

Пиши простым русским языком, как для человека без финансового образования.

ВАЖНО:
- Не выдумывай факты.
- Не придумывай идеи без новостей или подтверждений.
- Если сильных идей нет — честно напиши: сегодня ничего делать не нужно.
- Не используй сложные термины без объяснения.
- Не давай рекомендацию только по одной слабой новости.
- Максимум 2500 символов.

Мой портфель Freedom:

{FREEDOM_PORTFOLIO}

Мой портфель Paidax:

{PAIDAX_PORTFOLIO}

Мой Watch List:

{WATCH_LIST}

Новости за сутки:

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
Максимум 5 главных событий. Без длинного пересказа.

<b>2️⃣ Что важно сегодня?</b>
События, за которыми нужно следить сегодня. Если нет — напиши: важных событий на сегодня не найдено.

<b>3️⃣ Что влияет на мои деньги?</b>

<b>Freedom:</b>
Только важное для этого портфеля. Если ничего — напиши: существенных изменений нет.

<b>Paidax:</b>
Только важное для этого портфеля. Если ничего — напиши: существенных изменений нет.

<b>4️⃣ Watch List</b>
Пиши только если есть важные изменения по AVGO, AMZN, GOOGL, SK Hynix/SKHY, META.

<b>5️⃣ Возможности заработать</b>

<b>🧭 Скаут рынка:</b>
Найди до 3 идей в любых отраслях: IPO, ADR, split, spin-off, резкое движение, отчет, важный контракт.

<b>👔 Проверка портфельного управляющего:</b>
Объясни, подходит ли идея именно мне:
- долгосрочно
- только для спекуляции
- лучше пропустить

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

Собрано новостей: {len(news)}

Рекомендация:
⏳ Ждать. Не принимать решений без анализа.
"""

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

send_to_telegram(analysis_result)

print(f"Финиш скрипта UTC: {datetime.utcnow()}")
