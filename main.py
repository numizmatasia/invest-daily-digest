import os
import feedparser
import requests
from google import genai

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

client = genai.Client(api_key=GEMINI_API_KEY)

feeds = [
    "https://ir.thomsonreuters.com/rss/financial-news.xml",
    "https://feeds.bloomberg.com/wealth/news.rss",
    "https://www.nasdaqtrader.com/rss.aspx?feed=openmarketalerts",
    "http://feeds.marketwatch.com/marketwatch/topstories/",
    "https://search.cnbc.com/rs/search/combined/search.rss?partnerId=240&keywords=finance",
    "https://www.centralbanking.com/rss",
]

news = []

for feed_url in feeds:
    try:
        feed = feedparser.parse(feed_url)

        for entry in feed.entries[:10]:
            news.append(entry.title)

    except Exception:
        pass

raw_news = "\n".join(news)

portfolio = """
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

prompt = f"""
Ты главный инвестиционный аналитик.

Мой портфель:

{portfolio}

Новости:

{raw_news}

Правила:

1. Пиши только на русском языке.
2. Игнорируй незначимые новости.
3. Не повторяй одну мысль разными словами.
4. Не пиши общие рассуждения.
5. Если новостей по категории нет — так и напиши.
6. Не выдумывай факты и инвестиционные идеи.

Формат ответа:

📌 Главное за сутки
(максимум 5 пунктов)

📈 Влияние на мой портфель
- Уран
- Серебро
- Энергетика
- Акции
- Биткоин

🔎 Новые идеи вне портфеля
(только если найдены реальные идеи)

⚠️ Риски
(что может ухудшить ситуацию)

Максимум 1200 символов.
"""
