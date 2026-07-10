import os
import re
import json
import hashlib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlparse

import feedparser
import requests

VERSION = "TEMP-SAFETY-v2.2"
KZ_TIMEZONE = timezone(timedelta(hours=5))
LOOKBACK_HOURS = 48
REQUEST_TIMEOUT = 25
MAX_REPORT_EVENTS = 12
MAX_GDELT_RECORDS = 75
GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

RSS_FEEDS = [
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

PRESS_RELEASE_SOURCES = {"PR Newswire", "GlobeNewswire"}

# Временный словарь прямой релевантности. Финальная версия будет вынесена
# в отдельный каталог инструментов и компаний.
ENTITY_ALIASES = {
    "SKHY": ["SK Hynix", "SKHY"],
    "MU": ["Micron Technology", "Micron"],
    "AMAT": ["Applied Materials"],
    "AVGO": ["Broadcom"],
    "CCJ": ["Cameco"],
    "KZAPD": ["Kazatomprom", "NAC Kazatomprom"],
    "UROY": ["Uranium Royalty"],
    "IBIT": ["iShares Bitcoin Trust", "Bitcoin ETF"],
    "SIVR": ["abrdn Physical Silver Shares", "silver ETF"],
    "PSLV": ["Sprott Physical Silver Trust"],
    "XLE": ["Energy Select Sector SPDR", "US energy stocks"],
}

TOPIC_QUERIES = {
    "SEMICONDUCTORS": '("semiconductor" OR "chipmakers" OR "HBM" OR "AI chips")',
    "ENERGY": '("oil prices" OR "crude oil" OR "OPEC" OR "Iran oil")',
    "URANIUM": '("uranium" OR "nuclear power")',
    "PRECIOUS_METALS": '("gold prices" OR "silver prices")',
    "CRYPTO": '("bitcoin" OR "cryptocurrency market")',
    "US_MARKET": '("Federal Reserve" OR "US inflation" OR "US jobs report")',
}

EVENT_PATTERNS = {
    "earnings": [
        r"\bearnings?\b", r"\bfinancial results?\b", r"\bquarterly results?\b",
        r"\bannual results?\b", r"\brevenue\b", r"\bprofit\b", r"\bEPS\b",
    ],
    "guidance": [r"\bguidance\b", r"\boutlook\b", r"\bforecast\b"],
    "merger_acquisition": [
        r"\bmerger\b", r"\bacquisition\b", r"\bacquires?\b",
        r"\bto acquire\b", r"\btakeover\b", r"\basset sale\b",
    ],
    "capital_markets": [
        r"\bIPO\b", r"\blisting\b", r"\bADR\b", r"\boffering\b",
        r"\bbookbuild\b", r"\boversubscrib", r"\bconvertible notes?\b",
        r"\bsenior notes?\b", r"\bprivate placement\b",
        r"\bshare issuance\b", r"\bstock issuance\b",
    ],
    "capital_return": [r"\bdividend\b", r"\bbuyback\b", r"\bshare repurchase\b"],
    "distress": [
        r"\bbankruptcy\b", r"\bchapter 11\b", r"\bdefault\b",
        r"\brestructur", r"\binsolvenc",
    ],
    "regulatory": [
        r"\bregulatory approval\b", r"\bapproved by\b",
        r"\bregulatory clearance\b", r"\bantitrust\b", r"\bban\b",
    ],
    "legal_sanctions": [
        r"\blawsuit\b", r"\blitigation\b", r"\bsettlement\b",
        r"\bfine\b", r"\bsanction", r"\binvestigation\b",
    ],
    "management": [
        r"\bCEO\b", r"\bCFO\b", r"\bchief executive\b",
        r"\bchief financial\b", r"\bresigns?\b", r"\bsteps down\b",
    ],
    "operations": [
        r"\bshutdown\b", r"\bproduction halt\b", r"\bstrike\b",
        r"\baccident\b", r"\bmine closure\b", r"\bplant closure\b",
    ],
    "contract": [
        r"\bcontract award\b", r"\bawarded a contract\b", r"\bmajor contract\b",
    ],
    "market_move": [
        r"\bsurges?\b", r"\bslides?\b", r"\brall(?:y|ies)\b",
        r"\bplunges?\b", r"\bjumps?\b", r"\bfalls?\b",
        r"\brebound", r"\bselloff\b", r"\bmarket rout\b",
    ],
}

EVENT_WEIGHTS = {
    "earnings": 30,
    "guidance": 30,
    "merger_acquisition": 35,
    "capital_markets": 35,
    "capital_return": 25,
    "distress": 40,
    "regulatory": 35,
    "legal_sanctions": 30,
    "management": 20,
    "operations": 35,
    "contract": 20,
    "market_move": 20,
    "other": 5,
}

OFFICIAL_DOMAINS = {
    "sec.gov", "federalreserve.gov", "bls.gov", "bea.gov", "eia.gov",
    "treasury.gov", "nasdaqtrader.com", "fss.or.kr", "krx.co.kr",
    "nationalbank.kz", "kase.kz", "aix.kz", "iaea.org", "nrc.gov",
}

AUTHORITATIVE_MEDIA = {
    "reuters.com": ("REUTERS", 95),
    "bloomberg.com": ("BLOOMBERG", 95),
    "apnews.com": ("AP", 92),
    "ft.com": ("FINANCIAL_TIMES", 92),
    "wsj.com": ("WALL_STREET_JOURNAL", 92),
    "cnbc.com": ("CNBC", 85),
    "marketwatch.com": ("MARKETWATCH", 78),
}

AGGREGATOR_DOMAINS = {
    "investing.com", "finance.yahoo.com", "msn.com", "news.google.com",
    "seekingalpha.com",
}

PRESS_RELEASE_DOMAINS = {
    "prnewswire.com", "globenewswire.com", "businesswire.com",
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with",
    "from", "by", "after", "as", "at", "is", "are", "says", "said", "more",
    "than", "its", "this", "that", "will", "new", "us", "u", "s",
}


def now_kz():
    return datetime.now(timezone.utc).astimezone(KZ_TIMEZONE)


def clean_text(value):
    text = unescape(value or "")
    return " ".join(text.replace("\n", " ").replace("\r", " ").split()).strip()


def load_json_file(filename):
    try:
        with open(filename, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except Exception as error:
        print(f"WARNING: cannot read {filename}: {error}")
        return {}


def domain_from_url(url):
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def root_domain(domain):
    parts = domain.lower().split(".")
    if len(parts) <= 2:
        return domain.lower()
    return ".".join(parts[-2:])


def source_profile(domain, source_name=""):
    rd = root_domain(domain)

    if any(rd == d or domain.endswith("." + d) for d in OFFICIAL_DOMAINS):
        return {
            "group": "OFFICIAL",
            "trust": 100,
            "kind": "official",
            "counts_as_independent": True,
        }

    if rd in AUTHORITATIVE_MEDIA:
        group, trust = AUTHORITATIVE_MEDIA[rd]
        return {
            "group": group,
            "trust": trust,
            "kind": "authoritative_media",
            "counts_as_independent": True,
        }

    if rd in PRESS_RELEASE_DOMAINS or source_name in PRESS_RELEASE_SOURCES:
        return {
            "group": "ISSUER_RELEASE",
            "trust": 70,
            "kind": "issuer_statement",
            "counts_as_independent": False,
        }

    if rd in AGGREGATOR_DOMAINS:
        return {
            "group": "AGGREGATOR",
            "trust": 55,
            "kind": "aggregator",
            "counts_as_independent": False,
        }

    return {
        "group": f"MEDIA:{rd or source_name.lower()}",
        "trust": 65,
        "kind": "other_media",
        # Неизвестный сайт не считается независимым подтверждением автоматически.
        "counts_as_independent": False,
    }


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


def parse_gdelt_datetime(value):
    if not value:
        return None

    value = str(value).strip()
    formats = (
        "%Y%m%dT%H%M%SZ",
        "%Y%m%d%H%M%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def normalize_tokens(text):
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", clean_text(text).lower())
    return {word for word in words if len(word) > 2 and word not in STOPWORDS}


def title_similarity(left, right):
    a = normalize_tokens(left)
    b = normalize_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def classify_event_type(text):
    for event_type, patterns in EVENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return event_type
    return "other"


def is_material_press_release(title, summary):
    combined = f"{title} {summary}"
    event_type = classify_event_type(combined)
    return event_type != "other"


def build_user_entities(portfolio_data, watchlist_data):
    tickers = set()

    for positions in portfolio_data.values():
        if isinstance(positions, dict):
            tickers.update(str(ticker).upper() for ticker in positions)

    watchlist_names = {}
    for item in watchlist_data.get("watchlist", []):
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker", "")).upper().strip()
        name = clean_text(item.get("name", ""))
        if ticker:
            tickers.add(ticker)
            if name:
                watchlist_names[ticker] = name

    entities = {}
    for ticker in sorted(tickers):
        aliases = list(ENTITY_ALIASES.get(ticker, []))
        if ticker in watchlist_names:
            aliases.append(watchlist_names[ticker])
        aliases.append(ticker)
        aliases = list(dict.fromkeys(alias for alias in aliases if alias))
        # Не отправляем неоднозначный короткий тикер в GDELT без названия.
        searchable = [a for a in aliases if len(a) > 3 or " " in a]
        if searchable:
            entities[ticker] = searchable

    return entities


def collect_rss():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    articles = []
    working = []
    failed = []
    stats = {
        "raw_rss": 0,
        "filtered_pr": 0,
    }

    for source_name, feed_url in RSS_FEEDS:
        try:
            response = requests.get(
                feed_url,
                headers={"User-Agent": "Mozilla/5.0 InvestmentAssistant/2.2"},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            feed = feedparser.parse(response.content)

            if getattr(feed, "bozo", False) and not feed.entries:
                raise RuntimeError(
                    f"RSS parse error: {getattr(feed, 'bozo_exception', 'unknown')}"
                )

            accepted = 0
            for entry in feed.entries:
                title = clean_text(getattr(entry, "title", ""))
                summary = clean_text(getattr(entry, "summary", ""))
                link = clean_text(getattr(entry, "link", ""))
                published_at = parse_entry_datetime(entry)

                if not title or published_at is None or published_at < cutoff:
                    continue

                stats["raw_rss"] += 1

                if source_name in PRESS_RELEASE_SOURCES:
                    if not is_material_press_release(title, summary):
                        stats["filtered_pr"] += 1
                        continue

                articles.append(
                    {
                        "title": title,
                        "summary": summary,
                        "url": link,
                        "domain": domain_from_url(link),
                        "published_at": published_at,
                        "source_name": source_name,
                        "subject": "",
                        "direct_user_relevance": False,
                        "discovery_channel": "RSS",
                    }
                )
                accepted += 1

            working.append(f"{source_name}: {accepted}")

        except Exception as error:
            failed.append(f"{source_name}: {clean_text(str(error))[:160]}")

    return articles, working, failed, stats


def gdelt_request(query, label):
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "timespan": f"{LOOKBACK_HOURS}h",
        "maxrecords": str(MAX_GDELT_RECORDS),
        "sort": "datedesc",
    }
    response = requests.get(
        GDELT_ENDPOINT,
        params=params,
        headers={"User-Agent": "InvestmentAssistant/2.2"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()

    articles = []
    for item in payload.get("articles", []):
        title = clean_text(item.get("title", ""))
        url = clean_text(item.get("url", ""))
        if not title or not url:
            continue

        articles.append(
            {
                "title": title,
                "summary": "",
                "url": url,
                "domain": clean_text(item.get("domain", "")) or domain_from_url(url),
                "published_at": parse_gdelt_datetime(item.get("seendate")),
                "source_name": clean_text(item.get("domain", "")) or "GDELT",
                "subject": label,
                "direct_user_relevance": label in ENTITY_ALIASES or label.isupper() and label not in TOPIC_QUERIES,
                "discovery_channel": "GDELT",
            }
        )

    return articles


def collect_gdelt(user_entities):
    articles = []
    working = []
    failed = []

    # Прямые запросы по портфелю и watchlist.
    for ticker, aliases in user_entities.items():
        phrases = [f'"{alias}"' for alias in aliases[:3]]
        query = "(" + " OR ".join(phrases) + ")"
        try:
            found = gdelt_request(query, ticker)
            articles.extend(found)
            working.append(f"{ticker}: {len(found)}")
        except Exception as error:
            failed.append(f"{ticker}: {clean_text(str(error))[:160]}")

    # Тематический радар рынка.
    for topic, query in TOPIC_QUERIES.items():
        try:
            found = gdelt_request(query, topic)
            articles.extend(found)
            working.append(f"{topic}: {len(found)}")
        except Exception as error:
            failed.append(f"{topic}: {clean_text(str(error))[:160]}")

    return articles, working, failed


def infer_subject(article, user_entities):
    if article.get("subject"):
        return article["subject"], bool(article.get("direct_user_relevance"))

    title_lower = article["title"].lower()
    for ticker, aliases in user_entities.items():
        for alias in aliases:
            if alias.lower() in title_lower:
                return ticker, True

    topic_checks = {
        "SEMICONDUCTORS": ["semiconductor", "chipmaker", "hbm", "ai chip"],
        "ENERGY": ["oil", "crude", "opec", "iran"],
        "URANIUM": ["uranium", "nuclear"],
        "PRECIOUS_METALS": ["gold", "silver"],
        "CRYPTO": ["bitcoin", "crypto"],
        "US_MARKET": ["federal reserve", "inflation", "jobs report", "nasdaq", "s&p 500"],
    }
    for topic, terms in topic_checks.items():
        if any(term in title_lower for term in terms):
            return topic, False

    return "GENERAL", False


def deduplicate_articles(articles):
    seen = set()
    result = []

    for article in articles:
        key_source = (
            clean_text(article.get("title", "")).lower(),
            clean_text(article.get("url", "")).lower(),
        )
        raw = f"{key_source[0]}|{key_source[1]}".encode("utf-8", errors="ignore")
        key = hashlib.sha256(raw).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        result.append(article)

    return result


def cluster_articles(articles, user_entities):
    clusters = []

    valid_articles = [
        article for article in articles
        if article.get("published_at") is not None
    ]
    valid_articles.sort(key=lambda x: x["published_at"], reverse=True)

    for article in valid_articles:
        subject, direct = infer_subject(article, user_entities)
        article["subject"] = subject
        article["direct_user_relevance"] = direct
        article["event_type"] = classify_event_type(
            f"{article.get('title', '')} {article.get('summary', '')}"
        )
        article["source_profile"] = source_profile(
            article.get("domain", ""),
            article.get("source_name", ""),
        )
        day = article["published_at"].astimezone(KZ_TIMEZONE).date().isoformat()

        matched = None
        for cluster in clusters:
            if cluster["subject"] != subject:
                continue
            if cluster["event_type"] != article["event_type"]:
                continue
            if cluster["day"] != day:
                continue
            if title_similarity(cluster["representative_title"], article["title"]) >= 0.22:
                matched = cluster
                break

        if matched is None:
            clusters.append(
                {
                    "subject": subject,
                    "direct_user_relevance": direct,
                    "event_type": article["event_type"],
                    "day": day,
                    "representative_title": article["title"],
                    "articles": [article],
                }
            )
        else:
            matched["articles"].append(article)
            matched["direct_user_relevance"] = (
                matched["direct_user_relevance"] or direct
            )

    return clusters


def confirmation_status(cluster):
    independent_groups = set()
    official_present = False
    best_trust = 0
    source_groups = []

    for article in cluster["articles"]:
        profile = article["source_profile"]
        source_groups.append(profile["group"])
        best_trust = max(best_trust, profile["trust"])

        if profile["kind"] == "official":
            official_present = True

        if profile["counts_as_independent"]:
            independent_groups.add(profile["group"])

    if official_present:
        return {
            "code": "OFFICIAL_CONFIRMED",
            "label": "официально подтверждено",
            "independent_count": len(independent_groups),
            "best_trust": best_trust,
        }

    if len(independent_groups) >= 2:
        return {
            "code": "MULTI_SOURCE_CONFIRMED",
            "label": "подтверждено 2+ независимыми надежными источниками",
            "independent_count": len(independent_groups),
            "best_trust": best_trust,
        }

    if len(independent_groups) == 1 and best_trust >= 85:
        group = next(iter(independent_groups))
        return {
            "code": "RELIABLE_SINGLE_SOURCE",
            "label": f"один надежный источник: {group}",
            "independent_count": 1,
            "best_trust": best_trust,
        }

    # Много перепечаток и агрегаторов не превращают сообщение в подтвержденный факт.
    if len(cluster["articles"]) >= 2:
        return {
            "code": "REPEATED_NOT_INDEPENDENT",
            "label": "несколько публикаций, независимость не подтверждена",
            "independent_count": 0,
            "best_trust": best_trust,
        }

    return {
        "code": "UNVERIFIED_SINGLE_SOURCE",
        "label": "один непроверенный источник",
        "independent_count": 0,
        "best_trust": best_trust,
    }


def importance_score(cluster, confirmation):
    score = 0

    if cluster["direct_user_relevance"]:
        score += 45
    elif cluster["subject"] != "GENERAL":
        score += 20

    score += EVENT_WEIGHTS.get(cluster["event_type"], 5)

    if confirmation["code"] == "OFFICIAL_CONFIRMED":
        score += 20
    elif confirmation["code"] == "MULTI_SOURCE_CONFIRMED":
        score += 18
    elif confirmation["code"] == "RELIABLE_SINGLE_SOURCE":
        score += 15
    elif confirmation["code"] == "REPEATED_NOT_INDEPENDENT":
        score += 5

    newest = max(a["published_at"] for a in cluster["articles"])
    age_hours = (
        datetime.now(timezone.utc) - newest.astimezone(timezone.utc)
    ).total_seconds() / 3600
    if age_hours <= 12:
        score += 10
    elif age_hours <= 24:
        score += 5

    return min(score, 100)


def score_and_filter_clusters(clusters):
    results = []

    for cluster in clusters:
        confirmation = confirmation_status(cluster)
        score = importance_score(cluster, confirmation)

        # Важное правило:
        # один Reuters/Bloomberg/AP/FT/WSJ-источник по активу пользователя
        # показывается сразу. Подтверждение компании для показа не требуется.
        include = False
        if cluster["direct_user_relevance"] and score >= 60:
            include = True
        elif score >= 70:
            include = True
        elif (
            confirmation["code"] in {
                "OFFICIAL_CONFIRMED",
                "MULTI_SOURCE_CONFIRMED",
                "RELIABLE_SINGLE_SOURCE",
            }
            and score >= 55
        ):
            include = True

        if include:
            newest = max(a["published_at"] for a in cluster["articles"])
            results.append(
                {
                    **cluster,
                    "confirmation": confirmation,
                    "score": score,
                    "newest": newest,
                }
            )

    results.sort(
        key=lambda x: (
            x["direct_user_relevance"],
            x["score"],
            x["newest"],
        ),
        reverse=True,
    )
    return results


def source_names(cluster):
    names = []
    for article in cluster["articles"]:
        profile = article["source_profile"]
        name = profile["group"]
        if name not in names:
            names.append(name)
    return names


def build_report(rss_status, gdelt_status, stats, events):
    rss_working, rss_failed = rss_status
    gdelt_working, gdelt_failed = gdelt_status

    lines = [
        "⚠️ ВРЕМЕННЫЙ ДИАГНОСТИЧЕСКИЙ ДАЙДЖЕСТ",
        "",
        f"Версия: {VERSION}",
        "",
        "Правило подтверждения:",
        "• официальный источник — подтверждено;",
        "• 2+ независимых надежных источника — подтверждено;",
        "• один Reuters/Bloomberg/AP/FT/WSJ по активу пользователя — показывается сразу с маркировкой;",
        "• перепечатки одного сообщения не считаются независимыми подтверждениями.",
        "",
        "📡 Диагностика",
        f"• RSS работает: {len(rss_working)} из {len(RSS_FEEDS)}",
        f"• RSS ошибок: {len(rss_failed)}",
        f"• GDELT-запросов успешно: {len(gdelt_working)}",
        f"• GDELT-запросов с ошибкой: {len(gdelt_failed)}",
        f"• Сырых RSS-записей: {stats['raw_rss']}",
        f"• Отсеяно рекламных пресс-релизов: {stats['filtered_pr']}",
        "",
        "🚨 Важные события",
    ]

    if not events:
        lines.append(
            "События с достаточной важностью в доступных источниках не обнаружены. "
            "Это не означает, что рынок полностью проверен."
        )
    else:
        for event in events[:MAX_REPORT_EVENTS]:
            newest_kz = event["newest"].astimezone(KZ_TIMEZONE)
            direct_mark = "ПРЯМОЕ" if event["direct_user_relevance"] else "РЫНОЧНОЕ"
            lines.extend(
                [
                    "",
                    f"• [{direct_mark}] {event['subject']} — {event['representative_title']}",
                    f"  Важность: {event['score']}/100",
                    f"  Статус: {event['confirmation']['label']}",
                    f"  Независимых надежных групп: {event['confirmation']['independent_count']}",
                    f"  Источники/группы: {', '.join(source_names(event))}",
                    f"  Время: {newest_kz.strftime('%d.%m %H:%M')} KZ",
                ]
            )

    if rss_failed or gdelt_failed:
        lines.extend(["", "❌ Технические ошибки"])
        for item in (rss_failed + gdelt_failed)[:8]:
            lines.append(f"• {item}")

    lines.extend(
        [
            "",
            "⚠️ Ограничение",
            "Котировки и фундаментальные данные еще не подключены.",
            "Этот временный контур выявляет события и честно показывает уровень подтверждения, "
            "но пока не формирует команды на покупку или продажу.",
            "",
            f"🕒 Создано: {now_kz().strftime('%H:%M:%S')} KZ",
        ]
    )

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3800] + "\n\n...сообщение сокращено из-за лимита Telegram."
    return text


def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
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
            print(f"Telegram sent, attempt {attempt}")
            return
        except Exception as error:
            last_error = error
            print(f"Telegram error, attempt {attempt}: {error}")

    raise RuntimeError(f"Telegram delivery failed: {last_error}")


def main():
    print(f"START {VERSION} {now_kz().isoformat()}")

    portfolio_data = load_json_file("portfolio.json")
    watchlist_data = load_json_file("watchlist.json")
    user_entities = build_user_entities(portfolio_data, watchlist_data)

    rss_articles, rss_working, rss_failed, stats = collect_rss()
    gdelt_articles, gdelt_working, gdelt_failed = collect_gdelt(user_entities)

    articles = deduplicate_articles(rss_articles + gdelt_articles)
    clusters = cluster_articles(articles, user_entities)
    events = score_and_filter_clusters(clusters)

    report = build_report(
        (rss_working, rss_failed),
        (gdelt_working, gdelt_failed),
        stats,
        events,
    )
    print(report)
    send_to_telegram(report)

    print(f"FINISH {VERSION} {now_kz().isoformat()}")


if __name__ == "__main__":
    main()
