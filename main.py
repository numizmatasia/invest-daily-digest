import os
import feedparser
import requests

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

feeds = [
    "https://www.reutersagency.com/feed/?best-topics=markets",
    "https://world-nuclear-news.org/rss",
]

lines = []

for feed_url in feeds:
    try:
        feed = feedparser.parse(feed_url)

        for entry in feed.entries[:5]:
            lines.append(f"• {entry.title}")

    except Exception as e:
        lines.append(f"Ошибка чтения: {feed_url}")

message = "📈 Инвест дайджест\n\n"
message += "\n".join(lines[:15])

requests.post(
    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
    json={
        "chat_id": CHAT_ID,
        "text": message
    }
)

print("Done")
