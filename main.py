import os
import feedparser
import requests
from google import genai

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

client = genai.Client(api_key=GEMINI_API_KEY)

feeds = [
    "https://www.reutersagency.com/feed/?best-topics=business-finance",
    "https://world-nuclear-news.org/rss",
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
Ты инвестиционный аналитик.

Вот мой портфель:

{portfolio}

Вот новости за последние сутки:

{raw_news}

Сделай ответ на русском языке.

Формат:

1. Самые важные новости (не более 7 пунктов).
2. Влияние на мой портфель.
3. Что важно для урана.
4. Что важно для серебра.
5. Что важно для энергетики.
6. Есть ли новые инвестиционные идеи вне портфеля.
7. Не пиши воду и общие рассуждения.
8. Максимум 1500 символов.
"""

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt
)

digest = response.text

requests.post(
    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
    json={
        "chat_id": CHAT_ID,
        "text": digest
    }
)

print("Done")
