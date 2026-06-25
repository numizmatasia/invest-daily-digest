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
    "https://world-nuclear-news.org/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://seekingalpha.com/feed.xml",
    "https://www.investing.com/rss/news.rss",
    "https://oilprice.com/rss/main",
    "https://techcrunch.com/feed/",
    "https://www.marketwatch.com/rss/topstories",
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
            for entry in feed.entries[:3]:
                summary = getattr(entry, "summary", "")
                news.append(f"Заголовок: {entry.title}\nОписание: {summary}")
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
Ты мой личный инвестиционный помощник.

Мой портфель:

{portfolio}

Новости:

{raw_news}

Правила:

1. Пиши только на русском языке.
2. Пиши простым языком, как для человека без финансового образования.
3. Не используй слова:
   - инвестиционный тезис
   - волатильность
   - ликвидность
   - макроэкономика
   - нейтральный фон
4. Не пересказывай новости длинно.
5. Объясняй только то, что важно для моего портфеля.
6. Если новость не влияет на мой портфель — пропускай её.
7. Не выдумывай факты.
8. Не выдумывай инвестиционные идеи.
9. Если сегодня ничего важного не произошло — так и напиши.

Формат ответа:

📌 Что важно сегодня

Не более 5 пунктов.

Для каждого пункта:
- что произошло
- почему это хорошо или плохо

📊 Мои активы

🟢 Хорошие новости
Какие мои активы получили поддержку.

🟡 Без изменений
По каким активам ничего важного не произошло.

🔴 Плохие новости
Какие мои активы получили негативный сигнал.

📋 Что делать сегодня

Выбери только один вариант:

- Ничего не делать.
- Следить за ситуацией.
- Рассмотреть покупку.
- Рассмотреть продажу.

После выбора объясни причину максимум в 3 предложениях.

Максимум 1000 символов.
"""

# 3. Генерируем анализ через Gemini
try:
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    analysis_result = response.text

except Exception as e:
    print(f"Ошибка Gemini: {e}")

    analysis_result = f"""
📈 Инвест дайджест

Gemini временно недоступен.

Собрано новостей: {len(news)}

Проверьте следующий автоматический запуск.
"""

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
