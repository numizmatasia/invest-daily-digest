import os
import hashlib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html import unescape

import feedparser
import requests

VERSION = "TEMP-SAFETY-v2.0"
KZ_TIMEZONE = timezone(timedelta(hours=5))
LOOKBACK_HOURS = 48
MAX_ITEMS_IN_REPORT = 20
REQUEST_TIMEOUT = 20

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

FEEDS = [
    ("World Nuclear News", "https://world-nuclear-news.org/rss"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Seeking Alpha", "https://seekingalpha.com/feed.xml"),
    ("Investing.com", "https://www.investing.com/rss/news.rss"),
    ("OilPrice", "https://oilprice.com/rss/main"),
    ("TechCrunch", "https://techcrunch.com/feed/"),
    ("MarketWatch", "https://www.marketwatch.com/rss/topstories"),
    ("PR Newswire", "https://www.prnewswire.com/rss/news-releases-list.rss"),
    (
        "GlobeNewswire",
        "https://www.globenewswire.com/RssFeed/orgclass/1/"
        "feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies",
    ),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
    )
}


def now_kz():
    return datetime.now(timezone.utc).astimezone(KZ_TIMEZONE)


def clean_text(value):
    text = unescape(value or "")
    text = " ".join(text.replace("\n", " ").replace("\r", " ").split())
    return text.strip()


def parse_entry_datetime(entry):
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        value = getattr(entry, attr, None)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except Exception:
                pass

    for attr in ("published", "updated", "created"):
        value = getattr(entry, attr, None)
        if value:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except Exception:
                pass

    return None


def stable_item_id(title, link):
    raw = f"{title}|{link}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


def collect_news():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    working_sources = []
    failed_sources = []
    items = []
    seen = set()

    for source_name, feed_url in FEEDS:
        try:
            response = requests.get(
                feed_url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()

            parsed_feed = feedparser.parse(response.content)

            if getattr(parsed_feed, "bozo", False) and not parsed_feed.entries:
                raise RuntimeError(
                    f"RSS parsing error: {getattr(parsed_feed, 'bozo_exception', 'unknown')}"
                )

            source_count = 0

            for entry in parsed_feed.entries:
                title = clean_text(getattr(entry, "title", ""))
                link = clean_text(getattr(entry, "link", ""))
                published_at = parse_entry_datetime(entry)

                if not title:
                    continue

                if published_at is None or published_at < cutoff:
                    continue

                item_id = stable_item_id(title, link)
                if item_id in seen:
                    continue

                seen.add(item_id)
                source_count += 1
                items.append(
                    {
                        "source": source_name,
                        "title": title,
                        "link": link,
                        "published_at": published_at,
                    }
                )

            working_sources.append(
                {
                    "name": source_name,
                    "fresh_items": source_count,
                }
            )

        except Exception as error:
            failed_sources.append(
                {
                    "name": source_name,
                    "error": clean_text(str(error))[:180],
                }
            )

    items.sort(key=lambda item: item["published_at"], reverse=True)
    return working_sources, failed_sources, items


def build_report(working_sources, failed_sources, items):
    total_sources = len(FEEDS)
    working_count = len(working_sources)
    failed_count = len(failed_sources)
    fresh_count = len(items)

    if working_count < 6 or fresh_count == 0:
        first_line = "⛔ ДАННЫХ НЕДОСТАТОЧНО ДЛЯ ИНВЕСТИЦИОННОГО ВЫВОДА"
    else:
        first_line = "⚠️ ВРЕМЕННЫЙ ДИАГНОСТИЧЕСКИЙ ДАЙДЖЕСТ"

    lines = [
        first_line,
        "",
        f"Версия: {VERSION}",
        "",
        "Этот отчет проверяет только работу старых RSS-источников.",
        "Он НЕ видит текущие котировки, движение портфеля и весь мировой рынок.",
        "Поэтому он не выдает команды «покупать», «продавать» или «ждать».",
        "",
        "📡 Покрытие источников",
        f"• Всего настроено: {total_sources}",
        f"• Сработало: {working_count}",
        f"• Ошибок: {failed_count}",
        f"• Свежих записей за {LOOKBACK_HOURS} часов: {fresh_count}",
    ]

    if failed_sources:
        lines.extend(["", "❌ Не сработали:"])
        for source in failed_sources:
            lines.append(f"• {source['name']}: {source['error']}")

    lines.extend(["", "📰 Последние найденные публикации"])

    if not items:
        lines.append("Свежие публикации в доступных лентах не найдены.")
    else:
        for item in items[:MAX_ITEMS_IN_REPORT]:
            published_kz = item["published_at"].astimezone(KZ_TIMEZONE)
            lines.append(
                f"• {published_kz.strftime('%d.%m %H:%M')} — "
                f"{item['source']}: {item['title']}"
            )

    if fresh_count > MAX_ITEMS_IN_REPORT:
        lines.append(
            f"• Еще {fresh_count - MAX_ITEMS_IN_REPORT} записей не показаны "
            "из-за лимита длины сообщения."
        )

    lines.extend(
        [
            "",
            "⚠️ Ограничение",
            "Отсутствие новости в этом сообщении не означает, что события не было.",
            "До подключения официальных источников, рыночных цен и второго контура "
            "этот отчет нельзя использовать как профессиональную инвестиционную рекомендацию.",
            "",
            f"🕒 Создано: {now_kz().strftime('%H:%M:%S')} KZ",
        ]
    )

    return "\n".join(lines)


def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    if len(text) > 3900:
        text = text[:3800] + "\n\n...сообщение сокращено из-за лимита Telegram."

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }

    last_error = None

    for attempt in range(1, 3):
        try:
            response = requests.post(url, json=payload, timeout=20)
            response.raise_for_status()
            print(f"Telegram: сообщение отправлено, попытка {attempt}")
            return
        except Exception as error:
            last_error = error
            print(f"Telegram: ошибка попытки {attempt}: {error}")

    raise RuntimeError(f"Telegram delivery failed after 2 attempts: {last_error}")


def main():
    print(f"START {VERSION} at {now_kz().isoformat()}")

    working_sources, failed_sources, items = collect_news()
    report = build_report(working_sources, failed_sources, items)

    print(report)
    send_to_telegram(report)

    print(f"FINISH {VERSION} at {now_kz().isoformat()}")


if __name__ == "__main__":
    main()
