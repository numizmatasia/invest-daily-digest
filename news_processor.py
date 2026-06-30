import re


def clean_html(text):
    if not text:
        return ""

    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_text(text):
    if not text:
        return ""

    text = text.lower()
    text = re.sub(r"[^a-zа-я0-9\s$%.-]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def remove_duplicates(news_items):
    seen = set()
    unique_news = []

    for item in news_items:
        title = item.get("title", "")
        normalized_title = normalize_text(title)

        if normalized_title and normalized_title not in seen:
            seen.add(normalized_title)
            unique_news.append(item)

    return unique_news


def process_news(raw_items):
    cleaned_items = []

    for item in raw_items:
        cleaned_items.append({
            "source": item.get("source", ""),
            "title": clean_html(item.get("title", "")),
            "summary": clean_html(item.get("summary", "")),
            "link": item.get("link", "")
        })

    return remove_duplicates(cleaned_items)


def format_news_for_prompt(news_items):
    if not news_items:
        return "Нет свежих новостей от источников за текущий период."

    formatted = []

    for item in news_items:
        formatted.append(
            f"Источник: {item['source']}\n"
            f"Заголовок: {item['title']}\n"
            f"Описание: {item['summary']}\n"
            f"Ссылка: {item['link']}"
        )

    return "\n\n".join(formatted)
