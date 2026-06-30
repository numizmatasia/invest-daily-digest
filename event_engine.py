from collections import defaultdict


EVENT_TOPICS = {
    "ai_energy": {
        "title": "ИИ увеличивает спрос на электроэнергию",
        "keywords": [
            "ai power", "data center", "electricity demand", "power demand",
            "grid", "energy demand", "nuclear power", "uranium"
        ],
        "portfolio_links": ["XLE", "CCJ", "UROY", "KZAPD", "NVDA", "AMAT", "VRT"]
    },
    "uranium_nuclear": {
        "title": "Новости ядерной энергетики и урана",
        "keywords": [
            "uranium", "nuclear", "reactor", "nuclear power",
            "kazatomprom", "cameco", "small modular reactor", "smr"
        ],
        "portfolio_links": ["CCJ", "UROY", "KZAPD"]
    },
    "oil_energy": {
        "title": "Нефть и энергетический сектор",
        "keywords": [
            "oil", "crude", "opec", "brent", "wti",
            "energy stocks", "natural gas"
        ],
        "portfolio_links": ["XLE"]
    },
    "crypto": {
        "title": "Крипторынок и Bitcoin",
        "keywords": [
            "bitcoin", "btc", "crypto", "cryptocurrency",
            "ethereum", "etf inflows", "etf outflows"
        ],
        "portfolio_links": ["IBIT"]
    },
    "semiconductors": {
        "title": "Полупроводники и ИИ-чипы",
        "keywords": [
            "semiconductor", "chip", "chips", "gpu", "memory",
            "nvidia", "broadcom", "sk hynix", "micron", "amat"
        ],
        "portfolio_links": ["NVDA", "AVGO", "SKHY", "MU", "AMAT", "QQQM", "SPYG"]
    },
    "silver_gold": {
        "title": "Драгоценные металлы",
        "keywords": [
            "silver", "gold", "precious metals", "fed rates",
            "inflation", "safe haven"
        ],
        "portfolio_links": ["SIVR", "PSLV", "GLD"]
    },
    "market_general": {
        "title": "Общее движение рынка",
        "keywords": [
            "s&p 500", "nasdaq", "stocks", "market rally",
            "market selloff", "fed", "interest rates"
        ],
        "portfolio_links": ["SPY", "VT", "QQQM", "IXUS", "SPYM", "SPYG"]
    },
    "scout_events": {
        "title": "Потенциальные новые инвестиционные идеи",
        "keywords": [
            "ipo", "adr", "stock split", "spin-off", "spinoff",
            "merger", "acquisition", "index inclusion", "nasdaq listing",
            "nyse listing", "major contract"
        ],
        "portfolio_links": []
    }
}


def detect_events(news_items):
    events = defaultdict(lambda: {
        "title": "",
        "matched_news": [],
        "portfolio_links": [],
        "score": 0
    })

    for item in news_items:
        text = item.lower()

        for topic_id, topic_data in EVENT_TOPICS.items():
            matched_keywords = [
                keyword for keyword in topic_data["keywords"]
                if keyword.lower() in text
            ]

            if matched_keywords:
                events[topic_id]["title"] = topic_data["title"]
                events[topic_id]["matched_news"].append(item)
                events[topic_id]["portfolio_links"] = topic_data["portfolio_links"]
                events[topic_id]["score"] += len(matched_keywords)

    return rank_events(events)


def rank_events(events):
    ranked = []

    for topic_id, event in events.items():
        news_count = len(event["matched_news"])
        keyword_score = event["score"]
        portfolio_score = len(event["portfolio_links"])

        total_score = keyword_score + news_count + portfolio_score

        ranked.append({
            "id": topic_id,
            "title": event["title"],
            "importance": total_score,
            "news_count": news_count,
            "portfolio_links": event["portfolio_links"],
            "examples": event["matched_news"][:3]
        })

    ranked.sort(key=lambda x: x["importance"], reverse=True)

    return ranked[:5]


def format_events_for_prompt(events):
    if not events:
        return "Сильных инвестиционных событий по собранным новостям не найдено."

    lines = []

    for event in events:
        lines.append(f"Событие: {event['title']}")
        lines.append(f"Важность: {event['importance']}")
        lines.append(f"Количество связанных новостей: {event['news_count']}")

        if event["portfolio_links"]:
            lines.append("Связанные тикеры: " + ", ".join(event["portfolio_links"]))
        else:
            lines.append("Связанные тикеры: нет прямой связи с текущим портфелем")

        lines.append("Примеры новостей:")
        for example in event["examples"]:
            lines.append(example[:1000])

        lines.append("")

    return "\n".join(lines)
