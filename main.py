import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlencode, urlparse

import feedparser
import requests


VERSION = "STAGE4-QUALITY-v3.1-CONCRETE-ACTIONS"
MONTHLY_BUDGET_USD = 400
KZ_TIMEZONE = timezone(timedelta(hours=5))
LOOKBACK_HOURS = 48
REQUEST_TIMEOUT = 12
TELEGRAM_TIMEOUT = 20
GEMINI_TIMEOUT = 25
GEMINI_MODEL = "gemini-2.5-flash"
MAX_CONFIRMED_EVENTS = 5
MAX_RESEARCH_EVENTS = 3
TELEGRAM_SAFE_LIMIT = 3850

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

BASE_FEEDS = [
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
GOOGLE_NEWS_ENDPOINT = "https://news.google.com/rss/search"
REUTERS_SITEMAP_URL = (
    "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml"
)

ENTITY_ALIASES = {
    "SKHY": ["SK Hynix", "SK hynix"],
    "MU": ["Micron Technology", "Micron"],
    "AMAT": ["Applied Materials"],
    "AVGO": ["Broadcom"],
    "CCJ": ["Cameco"],
    "KZAPD": ["Kazatomprom", "NAC Kazatomprom"],
    "UROY": ["Uranium Royalty"],
    "IBIT": ["iShares Bitcoin Trust"],
    "SIVR": ["abrdn Physical Silver Shares"],
    "PSLV": ["Sprott Physical Silver Trust"],
    "XLE": ["Energy Select Sector SPDR"],
    "SPY": ["SPDR S&P 500 ETF Trust"],
    "VT": ["Vanguard Total World Stock ETF"],
    "QQQM": ["Invesco NASDAQ 100 ETF"],
    "IXUS": ["iShares Core MSCI Total International Stock ETF"],
    "SPYM": ["SPDR Portfolio S&P 500 ETF"],
}

TOPIC_TICKER_MAP = {
    "SEMICONDUCTORS": {"MU", "AMAT", "AVGO", "SKHY"},
    "ENERGY": {"XLE"},
    "URANIUM": {"CCJ", "KZAPD", "UROY"},
    "PRECIOUS_METALS": {"SIVR", "PSLV"},
    "CRYPTO": {"IBIT"},
    "US_MARKET": {"SPY", "SPYM", "VT", "QQQM", "IXUS"},
}

MARKET_RADAR_QUERY = (
    '("semiconductor" OR "chipmakers" OR "HBM" OR "AI chips" '
    'OR "uranium" OR "nuclear power" OR "oil prices" OR "crude oil" '
    'OR "gold prices" OR "silver prices" OR "bitcoin" '
    'OR "Federal Reserve" OR "US inflation" OR "US jobs report") when:2d'
)

EVENT_PATTERNS = {
    "earnings": [
        r"\bearnings?\b",
        r"\bfinancial results?\b",
        r"\bquarterly results?\b",
        r"\bannual results?\b",
        r"\brevenue\b",
        r"\bprofit\b",
        r"\beps\b",
    ],
    "guidance": [r"\bguidance\b", r"\boutlook\b", r"\bforecast\b"],
    "merger_acquisition": [
        r"\bmerger\b",
        r"\bacquisition\b",
        r"\bacquires?\b",
        r"\bto acquire\b",
        r"\btakeover\b",
        r"\basset sale\b",
    ],
    "capital_markets": [
        r"\bipo\b",
        r"\blisting\b",
        r"\badr\b",
        r"\boffering\b",
        r"\bprivate placement\b",
        r"\bshare issuance\b",
        r"\bstock issuance\b",
    ],
    "capital_return": [r"\bdividend\b", r"\bbuyback\b", r"\bshare repurchase\b"],
    "distress": [
        r"\bbankruptcy\b",
        r"\bchapter 11\b",
        r"\bdefault\b",
        r"\brestructur",
        r"\binsolvenc",
    ],
    "regulatory": [
        r"\bregulatory approval\b",
        r"\bapproved by\b",
        r"\bregulatory clearance\b",
        r"\bantitrust\b",
        r"\bban\b",
    ],
    "legal_sanctions": [
        r"\blawsuit\b",
        r"\blitigation\b",
        r"\bsettlement\b",
        r"\bfine\b",
        r"\bsanction",
        r"\binvestigation\b",
    ],
    "management": [
        r"\bceo\b",
        r"\bcfo\b",
        r"\bchief executive\b",
        r"\bchief financial\b",
        r"\bresigns?\b",
        r"\bsteps down\b",
    ],
    "operations": [
        r"\bshutdown\b",
        r"\bproduction halt\b",
        r"\bstrike\b",
        r"\baccident\b",
        r"\bmine closure\b",
        r"\bplant closure\b",
    ],
    "contract": [r"\bcontract award\b", r"\bawarded a contract\b", r"\bmajor contract\b"],
    "macro": [
        r"\bfederal reserve\b",
        r"\brate cut\b",
        r"\brate hike\b",
        r"\binflation\b",
        r"\bcpi\b",
        r"\bpce\b",
        r"\bjobs report\b",
        r"\bunemployment\b",
        r"\bgdp\b",
        r"\btreasury yield\b",
        r"\btariff",
    ],
    "market_move": [
        r"\bsurges?\b",
        r"\bslides?\b",
        r"\brall(?:y|ies)\b",
        r"\bplunges?\b",
        r"\bjumps?\b",
        r"\bfalls?\b",
        r"\brebound",
        r"\bselloff\b",
        r"\bmarket rout\b",
    ],
}

EVENT_TYPE_RU = {
    "earnings": "финансовая отчетность",
    "guidance": "изменение прогноза компании",
    "merger_acquisition": "слияние, покупка или продажа актива",
    "capital_markets": "размещение, листинг или привлечение капитала",
    "capital_return": "дивиденды или обратный выкуп",
    "distress": "финансовые трудности или реструктуризация",
    "regulatory": "регуляторное решение",
    "legal_sanctions": "судебное или санкционное событие",
    "management": "изменение руководства",
    "operations": "операционное событие",
    "contract": "контракт или заказ",
    "macro": "макроэкономическое или денежно-кредитное событие",
    "market_move": "существенное движение рынка или бумаги",
    "other": "корпоративное или рыночное событие",
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
    "macro": 35,
    "market_move": 18,
    "other": 5,
}

ACTION_LABELS_RU = {
    "NO_ACTION": "ДЕЙСТВИЙ НЕТ",
    "HOLD": "ОСТАВИТЬ БЕЗ ИЗМЕНЕНИЙ",
    "RESEARCH": "НЕ СОВЕРШАТЬ СДЕЛКУ ДО ПОДТВЕРЖДЕНИЯ",
    "WATCH": "ЖДАТЬ КОНКРЕТНОГО СИГНАЛА",
}
ALLOWED_ACTION_CODES = set(ACTION_LABELS_RU)

US_MACRO_TERMS = {
    "federal reserve",
    "fed ",
    "inflation",
    "cpi",
    "pce",
    "payroll",
    "jobs report",
    "unemployment",
    "gdp",
    "treasury yield",
    "rate cut",
    "rate hike",
    "tariff",
    "recession",
    "s&p 500",
    "nasdaq",
    "dow jones",
}

COMPANY_EVENT_TYPES = {
    "earnings",
    "guidance",
    "merger_acquisition",
    "capital_markets",
    "capital_return",
    "distress",
    "regulatory",
    "legal_sanctions",
    "management",
    "operations",
    "contract",
}

STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "from",
    "by",
    "after",
    "as",
    "at",
    "is",
    "are",
    "says",
    "said",
    "more",
    "than",
    "its",
    "this",
    "that",
    "will",
    "new",
    "us",
}

OFFICIAL_DOMAINS = {
    "sec.gov",
    "federalreserve.gov",
    "bls.gov",
    "bea.gov",
    "eia.gov",
    "treasury.gov",
    "nasdaqtrader.com",
    "fss.or.kr",
    "krx.co.kr",
    "nationalbank.kz",
    "kase.kz",
    "aix.kz",
    "iaea.org",
    "nrc.gov",
}

AUTHORITATIVE_MEDIA_DOMAINS = {
    "reuters.com": ("REUTERS", 98),
    "bloomberg.com": ("BLOOMBERG", 97),
    "apnews.com": ("AP", 95),
    "ft.com": ("FINANCIAL_TIMES", 94),
    "wsj.com": ("WALL_STREET_JOURNAL", 94),
    "cnbc.com": ("CNBC", 86),
    "marketwatch.com": ("MARKETWATCH", 82),
    "morningstar.com": ("MORNINGSTAR", 84),
    "yna.co.kr": ("YONHAP", 88),
    "nikkei.com": ("NIKKEI", 90),
    "barrons.com": ("BARRONS", 86),
}

LOW_QUALITY_DOMAINS = {"fool.com", "aol.com", "biggo.com"}
AGGREGATOR_DOMAINS = {
    "investing.com",
    "finance.yahoo.com",
    "yahoo.com",
    "msn.com",
    "news.google.com",
    "seekingalpha.com",
    "benzinga.com",
}
PRESS_RELEASE_DOMAINS = {"prnewswire.com", "globenewswire.com", "businesswire.com"}


def now_kz():
    return datetime.now(timezone.utc).astimezone(KZ_TIMEZONE)


def clean_text(value):
    return " ".join(
        unescape(str(value or "")).replace("\n", " ").replace("\r", " ").split()
    ).strip()


def trim_text(value, limit):
    value = clean_text(value)
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def normalize_tokens(text):
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", clean_text(text).lower())
    return {word for word in words if len(word) > 2 and word not in STOPWORDS}


def title_similarity(left, right):
    a, b = normalize_tokens(left), normalize_tokens(right)
    return 0.0 if not a or not b else len(a & b) / len(a | b)


def canonical_url(value):
    try:
        parsed = urlparse(clean_text(value))
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
    except Exception:
        return clean_text(value)


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


def parse_iso_datetime(value):
    try:
        parsed = datetime.fromisoformat(clean_text(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def domain_from_url(url):
    try:
        host = urlparse(url).netloc.lower().split(":")[0]
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def load_json_file(filename):
    try:
        data = json.loads(Path(filename).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as error:
        print(f"WARNING: cannot read {filename}: {error}")
        return {}


def build_user_entities(portfolio_data, watchlist_data):
    found = set()

    def scan(value):
        if isinstance(value, dict):
            ticker = str(value.get("ticker", "")).upper().strip()
            if ticker in ENTITY_ALIASES:
                found.add(ticker)
            for key, nested in value.items():
                key_ticker = str(key).upper().strip()
                if key_ticker in ENTITY_ALIASES:
                    found.add(key_ticker)
                scan(nested)
        elif isinstance(value, list):
            for item in value:
                scan(item)

    scan(portfolio_data)
    scan(watchlist_data)
    found.add("SKHY")
    return {ticker: ENTITY_ALIASES[ticker] for ticker in sorted(found)}


def google_news_url(query):
    return f"{GOOGLE_NEWS_ENDPOINT}?{urlencode({'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})}"


def build_radar_feeds(user_entities):
    names = [aliases[0] for aliases in user_entities.values() if aliases]
    entity_query = "(" + " OR ".join(f'"{name}"' for name in names) + ") when:2d"
    return [
        ("Radar: portfolio/watchlist", google_news_url(entity_query), "rss_radar"),
        ("Radar: market topics", google_news_url(MARKET_RADAR_QUERY), "rss_radar"),
        ("Radar: Reuters official", REUTERS_SITEMAP_URL, "reuters_sitemap"),
    ]


def classify_event_type(text):
    lowered = clean_text(text).lower()
    for event_type, patterns in EVENT_PATTERNS.items():
        if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in patterns):
            return event_type
    return "other"


def fetch_feed(feed_name, feed_url, feed_kind, cutoff):
    response = requests.get(
        feed_url,
        headers={"User-Agent": "Mozilla/5.0 InvestmentAssistant/3.1"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if getattr(feed, "bozo", False) and not feed.entries:
        raise RuntimeError(
            f"RSS parse error: {getattr(feed, 'bozo_exception', 'unknown')}"
        )

    articles = []
    raw_count = 0
    filtered_pr = 0

    for entry in feed.entries:
        title = clean_text(getattr(entry, "title", ""))
        summary = clean_text(getattr(entry, "summary", ""))
        published_at = parse_entry_datetime(entry)

        if not title or published_at is None or published_at < cutoff:
            continue

        raw_count += 1
        link = clean_text(getattr(entry, "link", ""))

        if (
            feed_name in PRESS_RELEASE_SOURCES
            and classify_event_type(f"{title} {summary}") == "other"
        ):
            filtered_pr += 1
            continue

        articles.append(
            {
                "title": title,
                "summary": summary,
                "url": link,
                "domain": domain_from_url(link),
                "published_at": published_at,
                "source_name": feed_name,
                "discovery_channel": feed_name,
                "feed_kind": feed_kind,
            }
        )

    return {
        "name": feed_name,
        "kind": feed_kind,
        "articles": articles,
        "raw_count": raw_count,
        "filtered_pr": filtered_pr,
    }


def fetch_reuters_sitemap(feed_name, feed_url, feed_kind, cutoff):
    response = requests.get(
        feed_url,
        headers={"User-Agent": "Mozilla/5.0 InvestmentAssistant/3.1"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    sm = "http://www.sitemaps.org/schemas/sitemap/0.9"
    news = "http://www.google.com/schemas/sitemap-news/0.9"
    articles = []

    for node in root.findall(f".//{{{sm}}}url"):
        link = clean_text(node.findtext(f"{{{sm}}}loc", default=""))
        title = clean_text(node.findtext(f".//{{{news}}}title", default=""))
        published_at = parse_iso_datetime(
            node.findtext(f".//{{{news}}}publication_date", default="")
        )
        if link and title and published_at and published_at >= cutoff:
            articles.append(
                {
                    "title": title,
                    "summary": "",
                    "url": link,
                    "domain": "reuters.com",
                    "published_at": published_at,
                    "source_name": "Reuters",
                    "discovery_channel": feed_name,
                    "feed_kind": feed_kind,
                }
            )

    return {
        "name": feed_name,
        "kind": feed_kind,
        "articles": articles,
        "raw_count": len(articles),
        "filtered_pr": 0,
    }


def collect_sources(user_entities):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    feeds = [(name, url, "base_rss") for name, url in BASE_FEEDS]
    feeds += build_radar_feeds(user_entities)

    collected = []
    base_working = []
    radar_working = []
    failures = []
    stats = {"raw_publications": 0, "filtered_pr": 0}

    def worker(item):
        name, url, kind = item
        if kind == "reuters_sitemap":
            return fetch_reuters_sitemap(name, url, kind, cutoff)
        return fetch_feed(name, url, kind, cutoff)

    with ThreadPoolExecutor(max_workers=min(8, len(feeds))) as pool:
        futures = {pool.submit(worker, item): item for item in feeds}
        for future in as_completed(futures):
            name, _, kind = futures[future]
            try:
                result = future.result()
                collected.extend(result["articles"])
                stats["raw_publications"] += result["raw_count"]
                stats["filtered_pr"] += result["filtered_pr"]
                if kind == "base_rss":
                    base_working.append(name)
                else:
                    radar_working.append(name)
            except Exception as error:
                failures.append({"source": name, "error": str(error)})

    unique = {}
    for article in collected:
        key = canonical_url(article.get("url"))
        if not key:
            key = hashlib.sha256(
                clean_text(article.get("title")).lower().encode()
            ).hexdigest()
        previous = unique.get(key)
        if previous is None or article["published_at"] > previous["published_at"]:
            unique[key] = article

    stats["deduplicated_publications"] = len(unique)
    return (
        list(unique.values()),
        sorted(base_working),
        sorted(radar_working),
        failures,
        stats,
    )


def infer_subjects(article, user_entities):
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    direct = []

    for ticker, aliases in user_entities.items():
        if any(
            re.search(rf"(?<!\w){re.escape(alias.lower())}(?!\w)", text)
            for alias in aliases
        ):
            direct.append(ticker)

    if direct:
        return sorted(set(direct)), True

    topics = []
    if any(term in text for term in ("semiconductor", "chip", "hbm", "memory")):
        topics.append("SEMICONDUCTORS")
    if any(term in text for term in ("oil", "crude", "opec", "hormuz", "energy")):
        topics.append("ENERGY")
    if any(term in text for term in ("uranium", "nuclear", "reactor")):
        topics.append("URANIUM")
    if any(term in text for term in ("silver", "precious metal")):
        topics.append("PRECIOUS_METALS")
    if any(term in text for term in ("bitcoin", "crypto")):
        topics.append("CRYPTO")
    if any(term in text for term in US_MACRO_TERMS):
        topics.append("US_MARKET")

    return topics or ["GENERAL"], False


def source_profile(article):
    domain = domain_from_url(article.get("url")) or article.get("domain", "")
    rd = ".".join(domain.lower().split(".")[-2:])

    if any(domain == item or domain.endswith("." + item) for item in OFFICIAL_DOMAINS):
        return {
            "group": "OFFICIAL",
            "trust": 100,
            "kind": "official",
            "independent": True,
        }

    if rd in AUTHORITATIVE_MEDIA_DOMAINS:
        group, trust = AUTHORITATIVE_MEDIA_DOMAINS[rd]
        return {
            "group": group,
            "trust": trust,
            "kind": "authoritative",
            "independent": True,
        }

    if rd in LOW_QUALITY_DOMAINS:
        return {
            "group": "LOW_QUALITY",
            "trust": 20,
            "kind": "low_quality",
            "independent": False,
        }

    if rd in PRESS_RELEASE_DOMAINS or article.get("source_name") in PRESS_RELEASE_SOURCES:
        return {
            "group": "ISSUER_RELEASE",
            "trust": 70,
            "kind": "issuer",
            "independent": False,
        }

    if rd in AGGREGATOR_DOMAINS:
        return {
            "group": "AGGREGATOR",
            "trust": 50,
            "kind": "aggregator",
            "independent": False,
        }

    return {
        "group": f"MEDIA:{rd or 'unknown'}",
        "trust": 62,
        "kind": "other",
        "independent": False,
    }


def valid_company_event(article, subjects, event_type):
    if event_type not in COMPANY_EVENT_TYPES:
        return True
    return any(subject in ENTITY_ALIASES for subject in subjects)


def valid_us_market_event(article, event_type):
    if "US_MARKET" not in article.get("subjects", []):
        return True
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    return (
        event_type in {"macro", "market_move", "regulatory"}
        and any(term in text for term in US_MACRO_TERMS)
    )


def same_physical_event(cluster, article):
    if cluster["event_type"] != article["event_type"]:
        return False
    if cluster["day"] != article["day"]:
        return False
    if set(cluster["subjects"]) & set(article["subjects"]):
        if title_similarity(cluster["seed_title"], article["title"]) >= 0.16:
            return True
        if (
            cluster["event_type"] == "earnings"
            and any(s in ENTITY_ALIASES for s in article["subjects"])
        ):
            return True
    return False


def cluster_articles(articles, user_entities):
    clusters = []
    rejected = {
        "invalid_company_event": 0,
        "invalid_us_market": 0,
        "low_quality": 0,
    }

    ordered = sorted(
        articles,
        key=lambda item: item.get("published_at")
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    for article in ordered:
        subjects, direct = infer_subjects(article, user_entities)
        event_type = classify_event_type(
            f"{article.get('title', '')} {article.get('summary', '')}"
        )
        article.update(
            {
                "subjects": subjects,
                "primary_subject": subjects[0],
                "direct_user_relevance": direct,
                "event_type": event_type,
                "day": article["published_at"]
                .astimezone(KZ_TIMEZONE)
                .date()
                .isoformat(),
                "source_profile": source_profile(article),
            }
        )

        if article["source_profile"]["kind"] == "low_quality":
            rejected["low_quality"] += 1
            continue
        if not valid_company_event(article, subjects, event_type):
            rejected["invalid_company_event"] += 1
            continue
        if not valid_us_market_event(article, event_type):
            rejected["invalid_us_market"] += 1
            continue

        matched = next(
            (cluster for cluster in clusters if same_physical_event(cluster, article)),
            None,
        )

        if matched:
            matched["articles"].append(article)
            matched["subjects"].update(subjects)
            matched["direct_user_relevance"] |= direct
        else:
            clusters.append(
                {
                    "primary_subject": subjects[0],
                    "subjects": set(subjects),
                    "direct_user_relevance": direct,
                    "event_type": event_type,
                    "day": article["day"],
                    "seed_title": article["title"],
                    "articles": [article],
                }
            )

    return clusters, rejected


def confirmation_status(cluster):
    independent = set()
    official = False
    issuer = False
    best = 0

    for article in cluster["articles"]:
        profile = article["source_profile"]
        best = max(best, profile["trust"])
        official |= profile["kind"] == "official"
        issuer |= profile["kind"] == "issuer"
        if profile["independent"]:
            independent.add(profile["group"])

    if official:
        return {
            "code": "OFFICIAL_CONFIRMED",
            "label": "официально подтверждено",
            "best_trust": best,
        }
    if len(independent) >= 2:
        return {
            "code": "MULTI_SOURCE_CONFIRMED",
            "label": "подтверждено 2+ независимыми источниками",
            "best_trust": best,
        }
    if len(independent) == 1 and best >= 82:
        return {
            "code": "RELIABLE_SINGLE_SOURCE",
            "label": f"один надежный источник: {next(iter(independent))}",
            "best_trust": best,
        }
    if issuer:
        return {
            "code": "ISSUER_STATEMENT",
            "label": "заявление компании, независимой проверки нет",
            "best_trust": best,
        }
    return {
        "code": "UNVERIFIED_SINGLE_SOURCE",
        "label": "один непроверенный источник",
        "best_trust": best,
    }


def choose_representative_article(cluster):
    return sorted(
        cluster["articles"],
        key=lambda article: (
            -article["source_profile"]["trust"],
            -article["published_at"].timestamp(),
        ),
    )[0]


def importance_score(cluster, confirmation):
    if cluster["direct_user_relevance"]:
        score = 45
    elif cluster["primary_subject"] != "GENERAL":
        score = 18
    else:
        score = 0

    score += EVENT_WEIGHTS.get(cluster["event_type"], 5)
    score += {
        "OFFICIAL_CONFIRMED": 20,
        "MULTI_SOURCE_CONFIRMED": 18,
        "RELIABLE_SINGLE_SOURCE": 15,
        "ISSUER_STATEMENT": 10,
    }.get(confirmation["code"], 0)
    return min(score, 100)


def material_topic_event(cluster):
    if cluster["direct_user_relevance"]:
        return True
    if cluster["primary_subject"] == "US_MARKET":
        return cluster["event_type"] in {"macro", "market_move", "regulatory"}
    return (
        cluster["primary_subject"] in TOPIC_TICKER_MAP
        and cluster["event_type"]
        in {
            "market_move",
            "regulatory",
            "operations",
            "capital_markets",
            "legal_sanctions",
            "distress",
            "macro",
        }
    )


def classify_event_buckets(clusters):
    confirmed = []
    research = []
    accepted = {
        "OFFICIAL_CONFIRMED",
        "MULTI_SOURCE_CONFIRMED",
        "RELIABLE_SINGLE_SOURCE",
        "ISSUER_STATEMENT",
    }

    for cluster in clusters:
        if not material_topic_event(cluster):
            continue

        confirmation = confirmation_status(cluster)
        representative = choose_representative_article(cluster)
        base = {
            **cluster,
            "confirmation": confirmation,
            "score": importance_score(cluster, confirmation),
            "representative": representative,
            "newest": max(article["published_at"] for article in cluster["articles"]),
        }

        if confirmation["code"] in accepted and base["score"] >= 60:
            base["display_tier"] = "CONFIRMED"
            confirmed.append(base)
        elif cluster["direct_user_relevance"] and base["score"] >= 50:
            base["display_tier"] = "RESEARCH"
            research.append(base)

    key = lambda item: (
        item["direct_user_relevance"],
        item["score"],
        item["newest"],
    )
    confirmed.sort(key=key, reverse=True)
    research.sort(key=key, reverse=True)
    return confirmed, research


def final_deduplicate(events):
    result = []

    for event in events:
        duplicate = None

        for kept in result:
            same_subject = bool(set(event["subjects"]) & set(kept["subjects"]))
            same_type = event["event_type"] == kept["event_type"]
            similar = (
                title_similarity(
                    event["representative"]["title"],
                    kept["representative"]["title"],
                )
                >= 0.12
            )
            if same_subject and same_type and similar:
                duplicate = kept
                break

        if duplicate:
            known_urls = {
                canonical_url(article.get("url"))
                for article in duplicate["articles"]
            }
            duplicate["articles"].extend(
                article
                for article in event["articles"]
                if canonical_url(article.get("url")) not in known_urls
            )
            duplicate["confirmation"] = confirmation_status(duplicate)
            duplicate["score"] = max(duplicate["score"], event["score"])
        else:
            result.append(event)

    return result


def select_events_for_report(confirmed, research):
    selected = (
        confirmed[:MAX_CONFIRMED_EVENTS]
        + research[:MAX_RESEARCH_EVENTS]
    )
    return final_deduplicate(selected)


def relation_text(event):
    direct = [
        subject
        for subject in sorted(event.get("subjects", []))
        if subject in ENTITY_ALIASES
    ]
    if direct:
        return "; ".join(f"{ticker} связан с событием напрямую" for ticker in direct)

    mapping = {
        "SEMICONDUCTORS": "Косвенная связь с полупроводниковой частью портфеля",
        "ENERGY": "Косвенная связь с XLE",
        "URANIUM": "Косвенная связь с урановой частью портфеля",
        "PRECIOUS_METALS": "Косвенная связь с серебром",
        "CRYPTO": "Косвенная связь с IBIT",
        "US_MARKET": "Системное влияние на широкие фондовые ETF",
    }
    return mapping.get(
        event.get("primary_subject", "GENERAL"),
        "Прямая связь с текущими позициями не установлена",
    )


def fallback_analysis(event, index):
    article = event["representative"]
    title = clean_text(article.get("title"))
    summary = clean_text(article.get("summary"))
    facts = trim_text(summary or title, 260)
    subject = next(
        (
            value
            for value in sorted(event["subjects"])
            if value in ENTITY_ALIASES
        ),
        event["primary_subject"],
    )
    confirmed = event["display_tier"] == "CONFIRMED"

    if confirmed:
        action_code = "HOLD"
        today_action = (
            "Сегодня позицию не увеличивать и не продавать только из-за этой новости."
        )
        decision_trigger = (
            "Пересмотреть решение после подтвержденного изменения прогноза прибыли, "
            "выручки, производства, дивидендов, ставки или другого числового показателя."
        )
        invalidation = (
            "Отменить влияние новости на решение, если новые данные ее не подтверждают "
            "или инвестиционный тезис компании не меняется."
        )
        reason = (
            "Событие подтверждено, но данных для изменения позиции или нового входа недостаточно."
        )
    else:
        action_code = "RESEARCH"
        today_action = "Сегодня никаких сделок по этой новости не совершать."
        decision_trigger = (
            "Вернуться к решению только после официального подтверждения "
            "или подтверждения минимум двумя независимыми надежными источниками."
        )
        invalidation = (
            "Игнорировать событие, если подтверждение не появится в течение 48 часов "
            "или первоначальная информация будет опровергнута."
        )
        reason = (
            "Сообщение недостаточно подтверждено и не может быть основанием для сделки."
        )

    return {
        "index": index,
        "title_ru": (
            f"{subject}: "
            f"{EVENT_TYPE_RU.get(event['event_type'], EVENT_TYPE_RU['other'])}"
        ),
        "what_happened_ru": facts,
        "relevance_ru": relation_text(event) + ".",
        "impact_label": "Не определено",
        "impact_reason_ru": (
            "Направление и сила влияния не доказаны числовыми данными."
        ),
        "watch_ru": decision_trigger,
        "action_code": action_code,
        "action_reason_ru": reason,
        "today_action_ru": today_action,
        "decision_trigger_ru": decision_trigger,
        "invalidation_ru": invalidation,
    }


def analyze_one_event_with_gemini(event, index):
    backup = fallback_analysis(event, index)

    if not GEMINI_API_KEY:
        return backup, False, "ключ отсутствует"

    payload = {
        "subject": sorted(event["subjects"]),
        "event_type": event["event_type"],
        "confirmation": event["confirmation"]["label"],
        "display_tier": event["display_tier"],
        "titles": [article["title"] for article in event["articles"][:5]],
        "summaries": [
            trim_text(article.get("summary", ""), 300)
            for article in event["articles"][:3]
        ],
        "relation": relation_text(event),
        "prices_available": False,
        "free_cash_available": False,
    }

    prompt = (
        "Ты редактор личного инвестиционного дайджеста. "
        "Ответь только одним JSON-объектом на русском языке. "
        "Не выдумывай факты, цены, уровни входа, проценты, даты отчетов "
        "или причины движения акций. "
        "Если причина движения не доказана источниками, прямо напиши, "
        "что причина не установлена. "
        "Не используй отдельные расплывчатые слова 'наблюдать', 'следить' "
        "или 'проверить дополнительно'. "
        "Каждая рекомендация должна отвечать на три вопроса: "
        "что конкретно делать сегодня; какое проверяемое событие изменит решение; "
        "при каком условии рекомендация отменяется. "
        "Поскольку текущие котировки, цена покупки и свободный остаток не переданы, "
        "нельзя рекомендовать немедленную покупку, продажу или точную сумму сделки. "
        "Для неподтвержденного события today_action_ru всегда должен запрещать сделку. "
        "Для подтвержденного события без числового изменения инвестиционного тезиса "
        "today_action_ru должен рекомендовать сохранить позицию без увеличения и продажи. "
        "Поля JSON: title_ru, what_happened_ru, relevance_ru, impact_label, "
        "impact_reason_ru, watch_ru, action_code, action_reason_ru, today_action_ru, "
        "decision_trigger_ru, invalidation_ru. "
        "action_code допускает только NO_ACTION, HOLD, WATCH или RESEARCH. "
        "BUY и SELL запрещены. "
        f"Событие: {json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        response = requests.post(
            (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
            ),
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.1,
                },
            },
            timeout=GEMINI_TIMEOUT,
        )
        response.raise_for_status()

        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        candidate = json.loads(text)

        if candidate.get("action_code") not in ALLOWED_ACTION_CODES:
            raise ValueError("invalid action_code")

        required = (
            "title_ru",
            "what_happened_ru",
            "relevance_ru",
            "impact_reason_ru",
            "watch_ru",
            "action_reason_ru",
            "today_action_ru",
            "decision_trigger_ru",
            "invalidation_ru",
        )

        if any(not clean_text(candidate.get(field)) for field in required):
            raise ValueError("missing required field")

        if event["display_tier"] != "CONFIRMED":
            candidate["action_code"] = "RESEARCH"
            candidate["today_action_ru"] = (
                "Сегодня никаких сделок по этой новости не совершать."
            )

        candidate["index"] = index
        return candidate, True, "ok"

    except Exception as error:
        return backup, False, str(error)


def extract_account_positions(portfolio_data):
    result = {}

    for account, value in (
        portfolio_data.items() if isinstance(portfolio_data, dict) else []
    ):
        text = json.dumps(value, ensure_ascii=False).upper()
        result[str(account)] = sorted(
            ticker
            for ticker in ENTITY_ALIASES
            if re.search(rf"\b{re.escape(ticker)}\b", text)
        )

    return result


def extract_watchlist_positions(watchlist_data):
    text = json.dumps(watchlist_data, ensure_ascii=False).upper()
    found = sorted(
        ticker
        for ticker in ENTITY_ALIASES
        if re.search(rf"\b{re.escape(ticker)}\b", text)
    )
    return sorted(set(found + ["SKHY"]))


def event_actions_by_ticker(events, analyses):
    result = {}

    for event, analysis in zip(events, analyses):
        tickers = [
            subject
            for subject in event["subjects"]
            if subject in ENTITY_ALIASES
        ]

        if not tickers and event["primary_subject"] in TOPIC_TICKER_MAP:
            tickers = sorted(TOPIC_TICKER_MAP[event["primary_subject"]])

        for ticker in tickers:
            result.setdefault(ticker, []).append(
                {**analysis, "tier": event["display_tier"]}
            )

    return result


def opportunity_lines(events):
    candidates = []

    for event in events:
        if event["display_tier"] != "CONFIRMED" or event["score"] < 75:
            continue

        direct = [
            subject
            for subject in event["subjects"]
            if subject in ENTITY_ALIASES
        ]

        if not direct and event["primary_subject"] not in {"US_MARKET", "GENERAL"}:
            candidates.append(
                f"• Тема {event['primary_subject']}: "
                f"{trim_text(event['representative']['title'], 150)}"
            )

    if not candidates:
        candidates.append(
            "• Подтвержденных новых кандидатов вне портфеля сегодня не найдено."
        )

    return ["", "🔎 Новые возможности", *candidates]


def choose_main_decision(analyses):
    if not analyses:
        return {
            "today_action_ru": (
                "Сегодня не менять портфель: подтвержденных событий, "
                "требующих сделки, не обнаружено."
            ),
            "decision_trigger_ru": (
                "Пересмотреть решение при появлении подтвержденного события, "
                "которое меняет прибыль, прогноз, производство или риски компании."
            ),
            "invalidation_ru": (
                "Текущая рекомендация перестает действовать после появления "
                "нового существенного подтвержденного события."
            ),
        }

    priority = {"RESEARCH": 4, "WATCH": 3, "HOLD": 2, "NO_ACTION": 1}
    return max(
        analyses,
        key=lambda item: priority.get(item.get("action_code", "NO_ACTION"), 0),
    )


def build_digest(
    events,
    analyses,
    portfolio_data,
    watchlist_data,
    stats,
    source_status,
    processing,
):
    main_decision = choose_main_decision(analyses)

    lines = [
        "📊 ЕЖЕДНЕВНЫЙ ИНВЕСТИЦИОННЫЙ ДАЙДЖЕСТ",
        f"Версия: {VERSION}",
        "",
        "📋 Конкретное решение на сегодня",
        f"• Действие: {trim_text(main_decision['today_action_ru'], 420)}",
        (
            "• Когда пересмотреть: "
            f"{trim_text(main_decision['decision_trigger_ru'], 420)}"
        ),
        (
            "• Когда отменить: "
            f"{trim_text(main_decision['invalidation_ru'], 420)}"
        ),
        "",
        "🔄 Существенные события",
    ]

    for event, analysis in zip(events, analyses):
        lines.extend(
            [
                f"• {analysis['title_ru']}",
                f"  Факт: {trim_text(analysis['what_happened_ru'], 210)}",
                f"  Решение: {trim_text(analysis['today_action_ru'], 230)}",
                (
                    "  Условие изменения: "
                    f"{trim_text(analysis['decision_trigger_ru'], 230)}"
                ),
                f"  Проверка: {event['confirmation']['label']}.",
            ]
        )

    if not events:
        lines.append("• Существенных подтвержденных событий не найдено.")

    action_map = event_actions_by_ticker(events, analyses)
    lines.extend(["", "📊 Влияние на мои инвестиции"])

    accounts = extract_account_positions(portfolio_data)

    for account, tickers in accounts.items():
        lines.append(f"• {account}")
        affected = [ticker for ticker in tickers if ticker in action_map]

        for ticker in affected:
            item = action_map[ticker][0]
            lines.append(
                f"  {ticker}: {trim_text(item['today_action_ru'], 210)}"
            )

        unaffected = [ticker for ticker in tickers if ticker not in action_map]

        if unaffected:
            lines.append(
                "  Без новых оснований менять позиции: "
                + ", ".join(unaffected)
                + "."
            )

    watch = extract_watchlist_positions(watchlist_data)
    lines.append("• Watch List")

    for ticker in [ticker for ticker in watch if ticker in action_map]:
        item = action_map[ticker][0]
        lines.append(
            f"  {ticker}: {trim_text(item['today_action_ru'], 210)}"
        )

    unaffected_watch = [
        ticker for ticker in watch if ticker not in action_map
    ]

    if unaffected_watch:
        lines.append(
            "  Без новых подтвержденных сигналов: "
            + ", ".join(unaffected_watch)
            + "."
        )

    lines.extend(
        [
            "",
            "💰 Инвестиционный бюджет",
            f"• Минимальный план месяца: {MONTHLY_BUDGET_USD} $.",
            (
                "• Сегодня сумму сделки не рассчитывать: текущие котировки, "
                "цена покупки и свободный остаток не подключены."
            ),
        ]
    )

    lines.extend(opportunity_lines(events))

    lines.extend(
        [
            "",
            "🧭 Полнота данных",
            (
                f"• RSS {len(source_status['base_working'])}/{len(BASE_FEEDS)}; "
                f"радар {len(source_status['radar_working'])}/3; "
                f"ошибок {len(source_status['failures'])}."
            ),
            (
                "• Публикаций после дедупликации: "
                f"{stats.get('deduplicated_publications', 0)}; "
                f"уникальных событий в отчете: {len(events)}."
            ),
            (
                "• Отсеяно ошибочных корпоративных событий: "
                f"{stats.get('invalid_company_event', 0)}; "
                f"ложных US_MARKET: {stats.get('invalid_us_market', 0)}; "
                f"низкокачественных: {stats.get('low_quality', 0)}."
            ),
            (
                "• Обработка текста: Gemini успешно "
                f"{processing['gemini_success']}/{len(events)}; "
                f"резервная логика {processing['fallback']}/{len(events)}."
            ),
            "",
            "⚠️ Решение основано только на доступных подтвержденных данных.",
            "⚠️ Без текущих цен бот не определяет точку входа и размер сделки.",
            f"🕒 Создано: {now_kz().strftime('%H:%M:%S')} KZ",
        ]
    )

    return "\n".join(lines)


def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID or BOT_TOKEN.startswith("0000000000:"):
        print(text)
        return

    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=TELEGRAM_TIMEOUT,
    )
    response.raise_for_status()


def run_self_tests():
    assert classify_event_type("Micron quarterly earnings revenue EPS") == "earnings"

    fake = {
        "title": "A company acquisition rumor",
        "summary": "",
        "subjects": ["US_MARKET"],
    }
    assert not valid_us_market_event(fake, "merger_acquisition")
    assert not valid_company_event({}, ["US_MARKET"], "merger_acquisition")
    assert valid_company_event({}, ["MU"], "earnings")

    first = {
        "title": "Micron reports quarterly earnings",
        "summary": "",
        "subjects": ["MU"],
        "event_type": "earnings",
        "day": "2026-07-21",
    }
    cluster = {
        "seed_title": first["title"],
        "subjects": {"MU"},
        "event_type": "earnings",
        "day": "2026-07-21",
    }
    second = {
        "title": "Micron posts quarterly results",
        "summary": "",
        "subjects": ["MU"],
        "event_type": "earnings",
        "day": "2026-07-21",
    }
    assert same_physical_event(cluster, second)

    decision = choose_main_decision(
        [
            {
                "action_code": "HOLD",
                "today_action_ru": "Оставить позицию.",
                "decision_trigger_ru": "После новых данных.",
                "invalidation_ru": "При опровержении.",
            },
            {
                "action_code": "RESEARCH",
                "today_action_ru": "Не совершать сделку.",
                "decision_trigger_ru": "После подтверждения.",
                "invalidation_ru": "Если не подтвердится.",
            },
        ]
    )
    assert decision["action_code"] == "RESEARCH"


def main():
    started = time.time()
    run_self_tests()

    portfolio_data = load_json_file("portfolio.json")
    watchlist_data = load_json_file("watchlist.json")
    entities = build_user_entities(portfolio_data, watchlist_data)

    (
        articles,
        base_working,
        radar_working,
        failures,
        stats,
    ) = collect_sources(entities)

    clusters, rejected = cluster_articles(articles, entities)
    stats.update(rejected)

    confirmed, research = classify_event_buckets(clusters)
    events = select_events_for_report(confirmed, research)

    analyses = []
    gemini_success = 0
    fallback_count = 0

    for index, event in enumerate(events):
        analysis, used_gemini, _ = analyze_one_event_with_gemini(event, index)
        analyses.append(analysis)
        gemini_success += int(used_gemini)
        fallback_count += int(not used_gemini)

    if len(analyses) != len(events):
        raise RuntimeError(
            f"Completeness gate failed: {len(analyses)}/{len(events)} events analyzed"
        )

    digest = build_digest(
        events,
        analyses,
        portfolio_data,
        watchlist_data,
        stats,
        {
            "base_working": base_working,
            "radar_working": radar_working,
            "failures": failures,
        },
        {
            "gemini_success": gemini_success,
            "fallback": fallback_count,
            "seconds": round(time.time() - started, 1),
        },
    )

    if len(digest) > TELEGRAM_SAFE_LIMIT:
        digest = (
            digest[: TELEGRAM_SAFE_LIMIT - 80].rstrip()
            + "\n\n⚠️ Текст сокращен по лимиту Telegram."
        )

    send_telegram(digest)


if __name__ == "__main__":
    main()
