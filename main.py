import os
import feedparser
import requests
from google import genai

# 1. Проверяем переменные окружения
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# 2. Инициализируем клиент Gemini
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

# Юзер-агент, чтобы сайты не блокировали скрипт как робота
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

for feed_url in feeds:
    try:
        # Скачиваем фид с заголовками, чтобы избежать блокировок
        resp = requests.get(feed_url, headers=headers, timeout=10)
        feed = feedparser.parse(resp.content)

        if feed.entries:
            for entry in feed.entries[:5]:
                news.append(entry.title)
        else:
            print(f"Предупреждение: Лента {feed_url} пуста или не распарсилась.")

    except Exception as e:
        print(f"Ошибка при чтении ленты {feed_url}: {e}")

raw_news = "\n".join(news)

if not raw_news:
    raw_news = "Нет свежих новостей от источников за текущий период."

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

# 3. Генерируем анализ через Gemini
try:
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    analysis_result = response.text
except Exception as e:
    print(f"Ошибка при запросе к Gemini API: {e}")
    raise e

# 4. Блок отправки сформированного ответа в Telegram
def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        res.raise_for_status()
        print("Анализ успешно отправлен в Telegram!")
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")
        if 'res' in locals():
            print(f"Ответ API Telegram: {res.text}")
        raise e

# Запуск отправки
send_to_telegram(analysis_result)
