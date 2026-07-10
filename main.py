import os
import subprocess
import sys
import re
import json
import time
import hashlib
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlencode, urlparse

import feedparser
import requests

VERSION = "TEMP-SAFETY-v2.9"
RELEASE_GATE_SCHEMA_VERSION = "1.0"
MONTHLY_BUDGET_USD = 400
KZ_TIMEZONE = timezone(timedelta(hours=5))
LOOKBACK_HOURS = 48
REQUEST_TIMEOUT = 12
TELEGRAM_TIMEOUT = 20
MAX_CONFIRMED_EVENTS = 2
MAX_RESEARCH_EVENTS = 1
MAX_EVENTS_IN_TELEGRAM = MAX_CONFIRMED_EVENTS + MAX_RESEARCH_EVENTS
TELEGRAM_SAFE_LIMIT = 3600

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TIMEOUT = 25

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
REUTERS_SITEMAP_URL = "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml"

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

MARKET_RADAR_QUERY = (
    '("semiconductor" OR "chipmakers" OR "HBM" OR "AI chips" '
    'OR "uranium" OR "nuclear power" OR "oil prices" OR "crude oil" '
    'OR "gold prices" OR "silver prices" OR "bitcoin" '
    'OR "Federal Reserve" OR "US inflation" OR "US jobs report") when:2d'
)

EVENT_PATTERNS = {
    "earnings": [r"\bearnings?\b", r"\bfinancial results?\b", r"\bquarterly results?\b", r"\bannual results?\b", r"\brevenue\b", r"\bprofit\b", r"\bEPS\b"],
    "guidance": [r"\bguidance\b", r"\boutlook\b", r"\bforecast\b"],
    "merger_acquisition": [r"\bmerger\b", r"\bacquisition\b", r"\bacquires?\b", r"\bto acquire\b", r"\btakeover\b", r"\basset sale\b"],
    "capital_markets": [r"\bIPO\b", r"\blisting\b", r"\bADR\b", r"\boffering\b", r"\bbookbuild\b", r"\boversubscrib", r"\bconvertible notes?\b", r"\bsenior notes?\b", r"\bprivate placement\b", r"\bshare issuance\b", r"\bstock issuance\b", r"\bshare sale\b", r"\bmarket debut\b", r"\bNasdaq debut\b", r"\bring the Nasdaq bell\b", r"\bhit the U\.?S\.? market\b"],
    "capital_return": [r"\bdividend\b", r"\bbuyback\b", r"\bshare repurchase\b"],
    "distress": [r"\bbankruptcy\b", r"\bchapter 11\b", r"\bdefault\b", r"\brestructur", r"\binsolvenc"],
    "regulatory": [r"\bregulatory approval\b", r"\bapproved by\b", r"\bregulatory clearance\b", r"\bantitrust\b", r"\bban\b"],
    "legal_sanctions": [r"\blawsuit\b", r"\blitigation\b", r"\bsettlement\b", r"\bfine\b", r"\bsanction", r"\binvestigation\b"],
    "management": [r"\bCEO\b", r"\bCFO\b", r"\bchief executive\b", r"\bchief financial\b", r"\bresigns?\b", r"\bsteps down\b"],
    "operations": [r"\bshutdown\b", r"\bproduction halt\b", r"\bstrike\b", r"\baccident\b", r"\bmine closure\b", r"\bplant closure\b"],
    "contract": [r"\bcontract award\b", r"\bawarded a contract\b", r"\bmajor contract\b"],
    "market_move": [r"\bsurges?\b", r"\bslides?\b", r"\brall(?:y|ies)\b", r"\bplunges?\b", r"\bjumps?\b", r"\bfalls?\b", r"\brebound", r"\bselloff\b", r"\bmarket rout\b"],
}

EVENT_WEIGHTS = {
    "earnings": 30, "guidance": 30, "merger_acquisition": 35,
    "capital_markets": 35, "capital_return": 25, "distress": 40,
    "regulatory": 35, "legal_sanctions": 30, "management": 20,
    "operations": 35, "contract": 20, "market_move": 18, "other": 5,
}

OPINION_PATTERNS = [
    r"\bJim Cramer\b", r"\bwhat I think\b", r"\bmy take\b",
    r"\bstands on\b", r"\bshould you buy\b", r"\bwhy I am buying\b",
    r"\bdumping all my\b", r"\brating upgrade\b", r"\brating downgrade\b",
    r"\banalyst says\b", r"\bquietly setting up\b",
    r"\bfair value debate\b", r"\bincredible news\b",
    r"\bjust got incredible\b", r"\bcould soar\b",
    r"\bis this stock a buy\b", r"\btop stock\b",
    r"\bstock prediction\b", r"\bprice target\b",
]

OFFICIAL_DOMAINS = {
    "sec.gov", "federalreserve.gov", "bls.gov", "bea.gov", "eia.gov",
    "treasury.gov", "nasdaqtrader.com", "fss.or.kr", "krx.co.kr",
    "nationalbank.kz", "kase.kz", "aix.kz", "iaea.org", "nrc.gov",
}

AUTHORITATIVE_MEDIA_DOMAINS = {
    "reuters.com": ("REUTERS", 98, 1),
    "bloomberg.com": ("BLOOMBERG", 97, 1),
    "apnews.com": ("AP", 95, 1),
    "ft.com": ("FINANCIAL_TIMES", 94, 1),
    "wsj.com": ("WALL_STREET_JOURNAL", 94, 1),
    "cnbc.com": ("CNBC", 86, 2),
    "marketwatch.com": ("MARKETWATCH", 82, 2),
    "theguardian.com": ("THE_GUARDIAN", 84, 2),
    "morningstar.com": ("MORNINGSTAR", 84, 2),
    "koreaherald.com": ("KOREA_HERALD", 82, 2),
    "yna.co.kr": ("YONHAP", 88, 2),
    "nikkei.com": ("NIKKEI", 90, 2),
    "barrons.com": ("BARRONS", 86, 2),
}

AUTHORITATIVE_MEDIA_NAMES = {
    "reuters": ("REUTERS", 98, 1),
    "bloomberg": ("BLOOMBERG", 97, 1),
    "associated press": ("AP", 95, 1),
    "ap": ("AP", 95, 1),
    "financial times": ("FINANCIAL_TIMES", 94, 1),
    "the wall street journal": ("WALL_STREET_JOURNAL", 94, 1),
    "wall street journal": ("WALL_STREET_JOURNAL", 94, 1),
    "cnbc": ("CNBC", 86, 2),
    "marketwatch": ("MARKETWATCH", 82, 2),
    "the guardian": ("THE_GUARDIAN", 84, 2),
    "morningstar": ("MORNINGSTAR", 84, 2),
    "the korea herald": ("KOREA_HERALD", 82, 2),
    "korea herald": ("KOREA_HERALD", 82, 2),
    "yonhap news agency": ("YONHAP", 88, 2),
    "nikkei asia": ("NIKKEI", 90, 2),
    "barron's": ("BARRONS", 86, 2),
}

AGGREGATOR_DOMAINS = {
    "investing.com", "finance.yahoo.com", "yahoo.com", "msn.com",
    "news.google.com", "seekingalpha.com", "benzinga.com",
}
AGGREGATOR_NAMES = {
    "investing.com", "yahoo finance", "yahoo", "msn",
    "seeking alpha", "benzinga", "google news",
}
LOW_QUALITY_DOMAINS = {
    "fool.com", "aol.com", "biggo.com",
}
LOW_QUALITY_NAMES = {
    "the motley fool", "motley fool", "aol", "biggo",
}
PRESS_RELEASE_DOMAINS = {"prnewswire.com", "globenewswire.com", "businesswire.com"}
MULTIPART_PUBLIC_SUFFIXES = {"co.kr", "co.uk", "com.sg", "com.au", "co.jp", "com.hk", "com.my", "co.nz", "com.br", "co.in"}
STOPWORDS = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "from", "by", "after", "as", "at", "is", "are", "says", "said", "more", "than", "its", "this", "that", "will", "new", "us", "u", "s"}
STRONG_CLUSTER_TYPES = {"earnings", "guidance", "merger_acquisition", "capital_markets", "capital_return", "distress", "regulatory", "legal_sanctions", "management", "operations"}


def now_kz():
    return datetime.now(timezone.utc).astimezone(KZ_TIMEZONE)


def clean_text(value):
    text = unescape(value or "")
    return " ".join(text.replace("\n", " ").replace("\r", " ").split()).strip()



def normalize_tokens(text):
    """Return normalized meaningful words for title comparison."""
    words = re.findall(
        r"[a-zA-Zа-яА-ЯёЁ0-9]+",
        clean_text(text).lower(),
    )
    return {
        word
        for word in words
        if len(word) > 2 and word not in STOPWORDS
    }


def title_similarity(left, right):
    """Jaccard similarity for clustering headlines about the same event."""
    left_tokens = normalize_tokens(left)
    right_tokens = normalize_tokens(right)

    if not left_tokens or not right_tokens:
        return 0.0

    return len(left_tokens & right_tokens) / len(
        left_tokens | right_tokens
    )


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
        host = urlparse(url).netloc.lower().split(":")[0]
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def registered_domain(domain):
    domain = (domain or "").lower().strip(".")
    parts = domain.split(".")
    if len(parts) <= 2:
        return domain
    tail2 = ".".join(parts[-2:])
    if tail2 in MULTIPART_PUBLIC_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return tail2


def source_profile(domain, source_name=""):
    rd = registered_domain(domain)
    name = clean_text(source_name).lower()

    if any(rd == item or domain.endswith("." + item) for item in OFFICIAL_DOMAINS):
        return {
            "group": "OFFICIAL",
            "trust": 100,
            "tier": 0,
            "kind": "official",
            "counts_as_independent": True,
        }

    if name in AUTHORITATIVE_MEDIA_NAMES:
        group, trust, tier = AUTHORITATIVE_MEDIA_NAMES[name]
        return {
            "group": group,
            "trust": trust,
            "tier": tier,
            "kind": "authoritative_media",
            "counts_as_independent": True,
        }

    if rd in AUTHORITATIVE_MEDIA_DOMAINS:
        group, trust, tier = AUTHORITATIVE_MEDIA_DOMAINS[rd]
        return {
            "group": group,
            "trust": trust,
            "tier": tier,
            "kind": "authoritative_media",
            "counts_as_independent": True,
        }

    if rd in LOW_QUALITY_DOMAINS or name in LOW_QUALITY_NAMES:
        return {
            "group": "LOW_QUALITY",
            "trust": 20,
            "tier": 9,
            "kind": "low_quality",
            "counts_as_independent": False,
        }

    if rd in PRESS_RELEASE_DOMAINS or source_name in PRESS_RELEASE_SOURCES:
        return {
            "group": "ISSUER_RELEASE",
            "trust": 70,
            "tier": 4,
            "kind": "issuer_statement",
            "counts_as_independent": False,
        }

    if rd in AGGREGATOR_DOMAINS or name in AGGREGATOR_NAMES:
        return {
            "group": "AGGREGATOR",
            "trust": 50,
            "tier": 5,
            "kind": "aggregator",
            "counts_as_independent": False,
        }

    return {
        "group": f"MEDIA:{rd or name or 'unknown'}",
        "trust": 62,
        "tier": 4,
        "kind": "other_media",
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


def extract_entry_source(entry, fallback_name):
    source = getattr(entry, "source", None)
    if source:
        try:
            title = clean_text(source.get("title", ""))
            href = clean_text(source.get("href", ""))
            if title or href:
                return title or fallback_name, href
        except Exception:
            pass
    return fallback_name, ""


def strip_source_suffix(title, source_name):
    if not source_name:
        return clean_text(title)
    pattern = r"\s*[-–—]\s*" + re.escape(clean_text(source_name)) + r"\s*$"
    return clean_text(re.sub(pattern, "", clean_text(title), flags=re.IGNORECASE))


def classify_event_type(text):
    for event_type, patterns in EVENT_PATTERNS.items():
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            return event_type
    return "other"


def is_opinion_title(title):
    return any(re.search(pattern, title, flags=re.IGNORECASE) for pattern in OPINION_PATTERNS)


def is_material_press_release(title, summary):
    return classify_event_type(f"{title} {summary}") != "other"


def build_user_entities(portfolio_data, watchlist_data):
    tickers = set()

    def scan(value):
        if isinstance(value, dict):
            direct_ticker = str(value.get("ticker", "")).upper().strip()
            if direct_ticker in ENTITY_ALIASES:
                tickers.add(direct_ticker)
            for key, nested in value.items():
                ticker = str(key).upper().strip()
                if ticker in ENTITY_ALIASES:
                    tickers.add(ticker)
                scan(nested)
        elif isinstance(value, list):
            for item in value:
                scan(item)

    scan(portfolio_data)
    scan(watchlist_data)
    tickers.add("SKHY")

    return {
        ticker: list(dict.fromkeys(ENTITY_ALIASES[ticker]))
        for ticker in sorted(tickers)
        if ticker in ENTITY_ALIASES
    }


def google_news_url(query):
    return f"{GOOGLE_NEWS_ENDPOINT}?{urlencode({'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})}"


def build_radar_feeds(user_entities):
    primary_names = [
        aliases[0]
        for aliases in user_entities.values()
        if aliases
    ]
    entity_query = (
        "("
        + " OR ".join(f'"{name}"' for name in primary_names)
        + ") when:2d"
    )

    return [
        (
            "Radar: portfolio/watchlist",
            google_news_url(entity_query),
            "rss_radar",
        ),
        (
            "Radar: market topics",
            google_news_url(MARKET_RADAR_QUERY),
            "rss_radar",
        ),
        (
            "Radar: Reuters official",
            REUTERS_SITEMAP_URL,
            "reuters_sitemap",
        ),
    ]


def fetch_feed(feed_name, feed_url, feed_kind, cutoff):
    response = requests.get(feed_url, headers={"User-Agent": "Mozilla/5.0 InvestmentAssistant/2.4"}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if getattr(feed, "bozo", False) and not feed.entries:
        raise RuntimeError(f"RSS parse error: {getattr(feed, 'bozo_exception', 'unknown')}")

    articles = []
    raw_count = 0
    filtered_pr = 0
    for entry in feed.entries:
        raw_title = clean_text(getattr(entry, "title", ""))
        summary = clean_text(getattr(entry, "summary", ""))
        link = clean_text(getattr(entry, "link", ""))
        published_at = parse_entry_datetime(entry)
        if not raw_title or published_at is None or published_at < cutoff:
            continue

        raw_count += 1
        source_name, source_href = extract_entry_source(entry, feed_name)
        title = strip_source_suffix(raw_title, source_name)

        if feed_name in PRESS_RELEASE_SOURCES and not is_material_press_release(title, summary):
            filtered_pr += 1
            continue

        articles.append({
            "title": title,
            "summary": summary,
            "url": link,
            "domain": domain_from_url(source_href) or domain_from_url(link),
            "published_at": published_at,
            "source_name": source_name,
            "discovery_channel": feed_name,
            "feed_kind": feed_kind,
        })

    return {"name": feed_name, "kind": feed_kind, "articles": articles, "raw_count": raw_count, "filtered_pr": filtered_pr}


def parse_iso_datetime(value):
    value = clean_text(value)
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def fetch_reuters_sitemap(feed_name, feed_url, feed_kind, cutoff):
    response = requests.get(
        feed_url,
        headers={
            "User-Agent": "Mozilla/5.0 InvestmentAssistant/2.5"
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    sitemap_ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
    news_ns = "http://www.google.com/schemas/sitemap-news/0.9"

    articles = []
    raw_count = 0

    for node in root.findall(f".//{{{sitemap_ns}}}url"):
        link = clean_text(
            node.findtext(f"{{{sitemap_ns}}}loc", default="")
        )
        title = clean_text(
            node.findtext(
                f".//{{{news_ns}}}title",
                default="",
            )
        )
        published_at = parse_iso_datetime(
            node.findtext(
                f".//{{{news_ns}}}publication_date",
                default="",
            )
        )

        if (
            not link
            or not title
            or published_at is None
            or published_at < cutoff
        ):
            continue

        raw_count += 1
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
        "raw_count": raw_count,
        "filtered_pr": 0,
    }


def collect_sources(user_entities):
    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=LOOKBACK_HOURS
    )
    specs = [
        (name, url, "base")
        for name, url in BASE_FEEDS
    ] + build_radar_feeds(user_entities)

    articles = []
    base_working = []
    radar_working = []
    failures = []
    stats = {
        "raw_base": 0,
        "raw_radar": 0,
        "filtered_pr": 0,
        "filtered_low_quality": 0,
        "filtered_opinion": 0,
    }

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {}

        for name, url, kind in specs:
            fetcher = (
                fetch_reuters_sitemap
                if kind == "reuters_sitemap"
                else fetch_feed
            )
            future = executor.submit(
                fetcher,
                name,
                url,
                kind,
                cutoff,
            )
            futures[future] = (name, kind)

        for future in as_completed(futures):
            name, kind = futures[future]
            try:
                result = future.result()
                articles.extend(result["articles"])
                stats["filtered_pr"] += result["filtered_pr"]
                status = (
                    f"{name}: {len(result['articles'])}"
                )

                if kind == "base":
                    base_working.append(status)
                    stats["raw_base"] += result["raw_count"]
                else:
                    radar_working.append(status)
                    stats["raw_radar"] += result["raw_count"]

            except Exception as error:
                failures.append(
                    {
                        "name": name,
                        "kind": kind,
                        "error": clean_text(str(error))[:140],
                    }
                )

    base_working.sort()
    radar_working.sort()
    failures.sort(key=lambda item: item["name"])

    return (
        articles,
        base_working,
        radar_working,
        failures,
        stats,
    )


def infer_subjects(article, user_entities):
    title_lower = clean_text(article.get("title", "")).lower()
    matches = []
    for ticker, aliases in user_entities.items():
        best_alias = None
        for alias in aliases:
            if re.search(r"(?<!\w)" + re.escape(alias.lower()) + r"(?!\w)", title_lower):
                if best_alias is None or len(alias) > len(best_alias):
                    best_alias = alias
        if best_alias:
            matches.append((ticker, best_alias))
    if matches:
        matches.sort(key=lambda item: len(item[1]), reverse=True)
        return [ticker for ticker, _ in matches], True

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
            return [topic], False
    return ["GENERAL"], False


def deduplicate_articles(articles):
    seen, result = set(), []
    for article in articles:
        title = re.sub(r"[^a-zа-яё0-9]+", " ", clean_text(article.get("title", "")).lower())
        group = source_profile(article.get("domain", ""), article.get("source_name", ""))["group"]
        key = hashlib.sha256(f"{' '.join(title.split())}|{group}".encode("utf-8", errors="ignore")).hexdigest()
        if key not in seen:
            seen.add(key)
            result.append(article)
    return result


def quality_filter_articles(articles):
    kept = []
    rejected = {
        "filtered_low_quality": 0,
        "filtered_opinion": 0,
    }

    for article in articles:
        profile = source_profile(
            article.get("domain", ""),
            article.get("source_name", ""),
        )

        if profile["kind"] == "low_quality":
            rejected["filtered_low_quality"] += 1
            continue

        if is_opinion_title(article.get("title", "")):
            rejected["filtered_opinion"] += 1
            continue

        kept.append(article)

    return kept, rejected


def cluster_articles(articles, user_entities):
    clusters = []
    valid = sorted((a for a in articles if a.get("published_at") is not None), key=lambda x: x["published_at"], reverse=True)
    for article in valid:
        subjects, direct = infer_subjects(article, user_entities)
        primary = subjects[0]
        event_type = classify_event_type(f"{article.get('title', '')} {article.get('summary', '')}")
        day = article["published_at"].astimezone(KZ_TIMEZONE).date().isoformat()
        article.update({
            "subjects": subjects,
            "primary_subject": primary,
            "direct_user_relevance": direct,
            "event_type": event_type,
            "source_profile": source_profile(article.get("domain", ""), article.get("source_name", "")),
            "is_opinion": is_opinion_title(article.get("title", "")),
        })

        matched = None
        for cluster in clusters:
            if cluster["primary_subject"] != primary or cluster["event_type"] != event_type or cluster["day"] != day:
                continue
            if event_type in STRONG_CLUSTER_TYPES or title_similarity(cluster["seed_title"], article["title"]) >= 0.30:
                matched = cluster
                break

        if matched is None:
            clusters.append({"primary_subject": primary, "subjects": set(subjects), "direct_user_relevance": direct, "event_type": event_type, "day": day, "seed_title": article["title"], "articles": [article]})
        else:
            matched["articles"].append(article)
            matched["subjects"].update(subjects)
            matched["direct_user_relevance"] = matched["direct_user_relevance"] or direct
    return clusters


def confirmation_status(cluster):
    independent_groups = set()
    official_present = False
    issuer_present = False
    best_trust = 0

    for article in cluster["articles"]:
        profile = article["source_profile"]
        best_trust = max(best_trust, profile["trust"])

        if profile["kind"] == "official":
            official_present = True
        if profile["kind"] == "issuer_statement":
            issuer_present = True
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
            "label": "подтверждено 2+ независимыми источниками",
            "independent_count": len(independent_groups),
            "best_trust": best_trust,
        }

    if len(independent_groups) == 1 and best_trust >= 82:
        group = next(iter(independent_groups))
        return {
            "code": "RELIABLE_SINGLE_SOURCE",
            "label": f"один надежный источник: {group}",
            "independent_count": 1,
            "best_trust": best_trust,
        }

    if issuer_present:
        return {
            "code": "ISSUER_STATEMENT",
            "label": "заявление компании, независимой проверки нет",
            "independent_count": 0,
            "best_trust": best_trust,
        }

    if len(cluster["articles"]) >= 2:
        return {
            "code": "REPEATED_NOT_INDEPENDENT",
            "label": "перепечатки без независимого подтверждения",
            "independent_count": 0,
            "best_trust": best_trust,
        }

    return {
        "code": "UNVERIFIED_SINGLE_SOURCE",
        "label": "один непроверенный источник",
        "independent_count": 0,
        "best_trust": best_trust,
    }


def choose_representative_article(cluster):
    return sorted(cluster["articles"], key=lambda a: (1 if a["is_opinion"] else 0, a["source_profile"]["tier"], -a["source_profile"]["trust"], -a["published_at"].timestamp()))[0]


def importance_score(cluster, confirmation):
    score = 0

    if cluster["direct_user_relevance"]:
        score += 45
    elif cluster["primary_subject"] != "GENERAL":
        score += 18

    score += EVENT_WEIGHTS.get(
        cluster["event_type"],
        5,
    )

    if confirmation["code"] == "OFFICIAL_CONFIRMED":
        score += 20
    elif confirmation["code"] == "MULTI_SOURCE_CONFIRMED":
        score += 18
    elif confirmation["code"] == "RELIABLE_SINGLE_SOURCE":
        score += 15
    elif confirmation["code"] == "ISSUER_STATEMENT":
        score += 10

    newest = max(
        article["published_at"]
        for article in cluster["articles"]
    )
    age_hours = (
        datetime.now(timezone.utc)
        - newest.astimezone(timezone.utc)
    ).total_seconds() / 3600

    if age_hours <= 12:
        score += 10
    elif age_hours <= 24:
        score += 5

    return min(score, 100)


def classify_event_buckets(clusters):
    confirmed = []
    research = []
    accepted_statuses = {
        "OFFICIAL_CONFIRMED",
        "MULTI_SOURCE_CONFIRMED",
        "RELIABLE_SINGLE_SOURCE",
        "ISSUER_STATEMENT",
    }
    research_statuses = {
        "REPEATED_NOT_INDEPENDENT",
        "UNVERIFIED_SINGLE_SOURCE",
    }
    research_event_types = STRONG_CLUSTER_TYPES | {"contract", "market_move"}

    for cluster in clusters:
        confirmation = confirmation_status(cluster)
        score = importance_score(cluster, confirmation)
        representative = choose_representative_article(cluster)

        base = {
            **cluster,
            "confirmation": confirmation,
            "score": score,
            "newest": max(
                article["published_at"]
                for article in cluster["articles"]
            ),
            "representative": representative,
        }

        is_confirmed = False
        if (
            cluster["direct_user_relevance"]
            and cluster["event_type"] in STRONG_CLUSTER_TYPES
            and confirmation["code"] in accepted_statuses
            and score >= 60
        ):
            is_confirmed = True
        elif (
            not cluster["direct_user_relevance"]
            and cluster["primary_subject"] != "GENERAL"
            and confirmation["code"] in {
                "OFFICIAL_CONFIRMED",
                "MULTI_SOURCE_CONFIRMED",
                "RELIABLE_SINGLE_SOURCE",
            }
            and score >= 60
        ):
            is_confirmed = True

        if is_confirmed:
            base["display_tier"] = "CONFIRMED"
            confirmed.append(base)
            continue

        # Не скрываем фактические материалы, относящиеся к портфелю,
        # только потому, что источник пока один или публикации зависимы.
        # Они идут в отдельный блок проверки, а не смешиваются с подтвержденными.
        if (
            cluster["direct_user_relevance"]
            and cluster["event_type"] in research_event_types
            and confirmation["code"] in research_statuses
            and score >= 50
        ):
            base["display_tier"] = "RESEARCH"
            research.append(base)

    sort_key = lambda item: (
        item["direct_user_relevance"],
        item["score"],
        item["newest"],
    )
    confirmed.sort(key=sort_key, reverse=True)
    research.sort(key=sort_key, reverse=True)
    return confirmed, research


def select_events_for_report(confirmed, research):
    selected = confirmed[:MAX_CONFIRMED_EVENTS]
    selected.extend(research[:MAX_RESEARCH_EVENTS])
    return selected


def score_and_filter_clusters(clusters):
    confirmed, research = classify_event_buckets(clusters)
    return select_events_for_report(confirmed, research)


def source_groups(cluster):
    result = []
    for article in cluster["articles"]:
        group = article["source_profile"]["group"]
        if group not in result:
            result.append(group)
    return result


def compact_subject(event):
    primary = event["primary_subject"]
    others = sorted(item for item in event["subjects"] if item != primary)
    return primary if not others else f"{primary}; связано: {', '.join(others[:2])}"


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
    "market_move": "существенное движение рынка или бумаги",
    "other": "корпоративное или рыночное событие",
}

ACTION_LABELS_RU = {
    "NO_ACTION": "ДЕЙСТВИЙ НЕТ",
    "HOLD": "ОСТАВИТЬ БЕЗ ИЗМЕНЕНИЙ",
    "WATCH": "НАБЛЮДАТЬ",
    "RESEARCH": "ПРОВЕРИТЬ ДОПОЛНИТЕЛЬНО",
}

ALLOWED_ACTION_CODES = set(ACTION_LABELS_RU)


def collect_ticker_locations(portfolio_data, watchlist_data):
    locations = {ticker: {"accounts": [], "watchlist": False} for ticker in ENTITY_ALIASES}

    def collect_from_value(value, account_name):
        if isinstance(value, dict):
            for key, nested in value.items():
                ticker = str(key).upper().strip()
                if ticker in locations and account_name not in locations[ticker]["accounts"]:
                    locations[ticker]["accounts"].append(account_name)
                collect_from_value(nested, account_name)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    ticker = str(item.get("ticker", "")).upper().strip()
                    if ticker in locations and account_name not in locations[ticker]["accounts"]:
                        locations[ticker]["accounts"].append(account_name)
                    collect_from_value(item, account_name)

    if isinstance(portfolio_data, dict):
        for account_name, positions in portfolio_data.items():
            collect_from_value(positions, str(account_name))

    if isinstance(watchlist_data, dict):
        for item in watchlist_data.get("watchlist", []):
            if isinstance(item, dict):
                ticker = str(item.get("ticker", "")).upper().strip()
                if ticker in locations:
                    locations[ticker]["watchlist"] = True

    # Пока SKHY ведется как отдельная задача пользователя, сохраняем его в списке наблюдения.
    locations["SKHY"]["watchlist"] = True
    return locations


def extract_account_positions(portfolio_data):
    accounts = {}

    def scan(value, result):
        if isinstance(value, dict):
            direct_ticker = str(value.get("ticker", "")).upper().strip()
            if direct_ticker in ENTITY_ALIASES:
                result.add(direct_ticker)
            for key, nested in value.items():
                ticker = str(key).upper().strip()
                if ticker in ENTITY_ALIASES:
                    result.add(ticker)
                scan(nested, result)
        elif isinstance(value, list):
            for item in value:
                scan(item, result)

    if isinstance(portfolio_data, dict):
        for account_name, positions in portfolio_data.items():
            tickers = set()
            scan(positions, tickers)
            accounts[str(account_name)] = sorted(tickers)

    return accounts


def extract_watchlist_positions(watchlist_data):
    tickers = []
    if isinstance(watchlist_data, dict):
        for item in watchlist_data.get("watchlist", []):
            if isinstance(item, dict):
                ticker = str(item.get("ticker", "")).upper().strip()
                if ticker in ENTITY_ALIASES and ticker not in tickers:
                    tickers.append(ticker)
    if "SKHY" not in tickers:
        tickers.append("SKHY")
    return sorted(tickers)


def event_actions_by_ticker(events, event_analyses):
    result = {}
    for index, event in enumerate(events):
        if index >= len(event_analyses):
            continue
        analysis = event_analyses[index]
        for subject in event.get("subjects", []):
            if subject not in ENTITY_ALIASES:
                continue
            result.setdefault(subject, []).append(
                {
                    "action_code": analysis.get("action_code", "RESEARCH"),
                    "title_ru": trim_text(analysis.get("title_ru", subject), 90),
                    "impact_label": analysis.get("impact_label", "Неясное"),
                    "tier": event.get("display_tier", "CONFIRMED"),
                }
            )
    return result


def account_display_name(name):
    value = clean_text(name)
    lower = value.lower()
    if "freedom" in lower:
        return "Freedom"
    if "paidax" in lower:
        return "Paidax"
    return value or "Портфель"


def normalize_core_accounts(account_positions):
    normalized = {
        "Freedom": {"found": False, "tickers": set()},
        "Paidax": {"found": False, "tickers": set()},
    }
    extras = []

    for raw_name, tickers in account_positions.items():
        display = account_display_name(raw_name)
        ticker_set = set(tickers)
        if display in normalized:
            normalized[display]["found"] = True
            normalized[display]["tickers"].update(ticker_set)
        else:
            extras.append((display, sorted(ticker_set), True))

    result = [
        ("Freedom", sorted(normalized["Freedom"]["tickers"]), normalized["Freedom"]["found"]),
        ("Paidax", sorted(normalized["Paidax"]["tickers"]), normalized["Paidax"]["found"]),
    ]
    result.extend(extras)
    return result


def portfolio_lines(account_positions, watchlist_tickers, events, event_analyses):
    action_map = event_actions_by_ticker(events, event_analyses)
    lines = ["", "📊 Влияние на мои инвестиции"]

    for name, tickers, found in normalize_core_accounts(account_positions):
        lines.append(f"• {name}")
        if not found:
            lines.append(
                "  Данные этого портфеля в portfolio.json не распознаны. "
                "Вывод о влиянии делать нельзя."
            )
            continue

        affected = [ticker for ticker in tickers if ticker in action_map]
        unaffected = [ticker for ticker in tickers if ticker not in action_map]

        if affected:
            for ticker in affected:
                item = action_map[ticker][0]
                label = ACTION_LABELS_RU.get(
                    item["action_code"],
                    "ПРОВЕРИТЬ ДОПОЛНИТЕЛЬНО",
                )
                lines.append(f"  {ticker}: {label} — {item['title_ru']}")
        else:
            lines.append(
                "  По доступным источникам новых существенных событий по позициям не найдено."
            )

        if unaffected:
            lines.append(
                "  Без новых существенных событий: "
                + ", ".join(unaffected)
                + "."
            )

    lines.append("• Watch List")
    affected_watch = [ticker for ticker in watchlist_tickers if ticker in action_map]
    unaffected_watch = [ticker for ticker in watchlist_tickers if ticker not in action_map]

    if affected_watch:
        for ticker in affected_watch:
            item = action_map[ticker][0]
            label = ACTION_LABELS_RU.get(
                item["action_code"],
                "ПРОВЕРИТЬ ДОПОЛНИТЕЛЬНО",
            )
            lines.append(f"  {ticker}: {label} — {item['title_ru']}")
    else:
        lines.append(
            "  По доступным источникам новых существенных событий не найдено."
        )

    if unaffected_watch:
        lines.append(
            "  Без новых существенных событий: "
            + ", ".join(unaffected_watch)
            + "."
        )

    return lines

def information_background_lines(account_positions, watchlist_tickers, events, event_analyses):
    action_map = event_actions_by_ticker(events, event_analyses)

    def background_for(tickers):
        labels = []
        has_research = False
        for ticker in tickers:
            for item in action_map.get(ticker, []):
                labels.append(item.get("impact_label", "Неясное"))
                if item.get("tier") == "RESEARCH":
                    has_research = True
        if not labels:
            return "нейтральный: новых подтвержденных событий не найдено"
        if has_research:
            return "неясный: есть сообщение, которое требует проверки"
        unique = set(labels)
        if "Отрицательное" in unique and "Положительное" in unique:
            return "смешанный"
        if "Смешанное" in unique or len(unique) > 1:
            return "смешанный"
        if unique == {"Положительное"}:
            return "положительный информационный фон"
        if unique == {"Отрицательное"}:
            return "отрицательный информационный фон"
        return "неясный: требуется дополнительная проверка"

    lines = ["", "📊 Информационный фон, не прогноз цены"]
    for raw_name, tickers in sorted(
        account_positions.items(),
        key=lambda item: (
            0 if "freedom" in item[0].lower() else
            1 if "paidax" in item[0].lower() else 2,
            item[0].lower(),
        ),
    ):
        lines.append(
            f"• {account_display_name(raw_name)}: {background_for(tickers)}."
        )
    lines.append(
        f"• Watch List: {background_for(watchlist_tickers)}."
    )
    return lines


def overall_action(event_analyses):
    if not event_analyses:
        return (
            "ДЕЙСТВИЙ НЕТ",
            "Подтвержденных изменений, требующих действий, не обнаружено.",
        )

    priority = {
        "RESEARCH": 4,
        "WATCH": 3,
        "HOLD": 2,
        "NO_ACTION": 1,
    }
    chosen = max(
        event_analyses,
        key=lambda item: priority.get(item.get("action_code", "RESEARCH"), 4),
    )
    code = chosen.get("action_code", "RESEARCH")
    label = ACTION_LABELS_RU.get(code, "ПРОВЕРИТЬ ДОПОЛНИТЕЛЬНО")
    reason = trim_text(
        chosen.get("action_reason_ru", "Требуется дополнительная проверка."),
        260,
    )
    return label, reason


def budget_lines():
    return [
        "",
        "💰 Инвестиционный бюджет",
        f"• Минимальный план месяца: {MONTHLY_BUDGET_USD} $.",
        (
            "• Сегодня: не распределять бюджет автоматически. "
            "Котировки, свободный остаток и допустимый размер сделки пока не подключены."
        ),
    ]


def opportunity_lines():
    return [
        "",
        "🔎 Новые возможности",
        (
            "Кандидаты на покупку временным контуром не формируются: "
            "для этого нужны проверенные котировки, фундаментальные данные, "
            "ликвидность и расчет размера позиции."
        ),
    ]


def relation_text(event, ticker_locations):
    direct_tickers = [
        subject for subject in sorted(event.get("subjects", []))
        if subject in ticker_locations
    ]

    parts = []
    for ticker in direct_tickers:
        item = ticker_locations[ticker]
        if item["accounts"]:
            parts.append(f"{ticker} находится в портфеле: {', '.join(item['accounts'])}")
        elif item["watchlist"]:
            parts.append(f"{ticker} находится в списке наблюдения")

    if parts:
        return "; ".join(parts)

    primary = event.get("primary_subject", "GENERAL")
    if primary == "SEMICONDUCTORS":
        return "Косвенная связь с позициями MU, AMAT, AVGO и наблюдаемой SKHY"
    if primary == "ENERGY":
        return "Косвенная связь с XLE и энергетической частью портфеля"
    if primary == "URANIUM":
        return "Косвенная связь с CCJ, KZAPD и UROY"
    if primary == "PRECIOUS_METALS":
        return "Косвенная связь с SIVR и PSLV"
    if primary == "CRYPTO":
        return "Косвенная связь с IBIT"
    if primary == "US_MARKET":
        return "Влияние на широкие фондовые позиции SPY, SPYM, VT, QQQM и IXUS"
    return "Прямая связь с текущими позициями не установлена"


def trim_text(value, limit):
    value = clean_text(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def fallback_analysis(event, ticker_locations, index):
    subject = compact_subject(event)
    event_type = EVENT_TYPE_RU.get(
        event.get("event_type", "other"),
        EVENT_TYPE_RU["other"],
    )
    relation = relation_text(event, ticker_locations)

    return {
        "index": index,
        "title_ru": f"{subject}: {event_type}",
        "what_happened_ru": (
            "Обнаружено значимое событие, но автоматический разбор содержания недоступен. "
            "Для точного вывода требуется проверить первичный материал."
        ),
        "relevance_ru": relation + ".",
        "impact_label": "Неясное",
        "impact_reason_ru": (
            "Без полного текста, котировки и фундаментальных данных направление влияния надежно не определяется."
        ),
        "watch_ru": "Проверить первичный источник, параметры события и реакцию цены.",
        "action_code": "RESEARCH",
        "action_reason_ru": (
            "Событие связано с портфелем или списком наблюдения, но данных недостаточно для изменения позиции."
        ),
    }


def build_gemini_events(events, ticker_locations):
    payload = []
    for index, event in enumerate(events[:MAX_EVENTS_IN_TELEGRAM]):
        titles = []
        for article in event.get("articles", []):
            title = clean_text(article.get("title", ""))
            if title and title not in titles:
                titles.append(title)
            if len(titles) >= 5:
                break

        payload.append(
            {
                "index": index,
                "subject": compact_subject(event),
                "event_type": EVENT_TYPE_RU.get(event.get("event_type", "other"), EVENT_TYPE_RU["other"]),
                "importance": event.get("score", 0),
                "confirmation": event.get("confirmation", {}).get("label", "статус не определен"),
                "sources": source_groups(event)[:5],
                "portfolio_relation": relation_text(event, ticker_locations),
                "verification_tier": event.get("display_tier", "CONFIRMED"),
                "source_titles": titles,
                "source_summaries": [
                    trim_text(article.get("summary", ""), 260)
                    for article in event.get("articles", [])[:3]
                    if clean_text(article.get("summary", ""))
                ],
            }
        )
    return payload


def extract_gemini_text(response_json):
    candidates = response_json.get("candidates", [])
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    texts = [part.get("text", "") for part in parts if part.get("text")]
    if not texts:
        raise RuntimeError("Gemini returned no text")
    return "".join(texts)


def has_russian_text(value):
    value = clean_text(value)
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", value))
    latin = len(re.findall(r"[A-Za-z]", value))
    if cyrillic < 3:
        return False
    return latin <= max(18, cyrillic)


def contains_raw_source_title(value, event):
    normalized_value = clean_text(value).lower()
    for article in event.get("articles", []):
        raw_title = clean_text(article.get("title", ""))
        if len(raw_title) >= 24 and raw_title.lower() in normalized_value:
            return True
    return False


def valid_russian_analysis(candidate, event):
    required_text_fields = (
        "title_ru",
        "what_happened_ru",
        "relevance_ru",
        "impact_reason_ru",
        "watch_ru",
        "action_reason_ru",
    )
    if candidate.get("action_code") not in ALLOWED_ACTION_CODES:
        return False
    if candidate.get("impact_label") not in {
        "Положительное",
        "Отрицательное",
        "Смешанное",
        "Неясное",
    }:
        return False
    for field in required_text_fields:
        value = candidate.get(field, "")
        if not value or not has_russian_text(value):
            return False
        if contains_raw_source_title(value, event):
            return False
    return True


def analyze_events_in_russian(events, ticker_locations):
    selected = events[:MAX_EVENTS_IN_TELEGRAM]
    fallback = [
        fallback_analysis(event, ticker_locations, index)
        for index, event in enumerate(selected)
    ]

    if not selected:
        return fallback, "не требовался"

    if not GEMINI_API_KEY:
        return fallback, "ключ Gemini отсутствует — использован русский резервный шаблон"

    input_events = build_gemini_events(selected, ticker_locations)
    prompt = (
        "Ты редактор личного инвестиционного дайджеста. Проанализируй события ниже. "
        "Ответь строго по-русски и только в заданной JSON-структуре. "
        "Не копируй английские заголовки. Не выдумывай факты, цифры или причины, которых нет во входных данных. "
        "Если заголовков недостаточно, прямо напиши: 'Недостаточно данных в заголовках'. "
        "Для каждого события объясни: что произошло; какое отношение оно имеет к указанным позициям или списку наблюдения; "
        "каково вероятное направление влияния — Положительное, Отрицательное, Смешанное или Неясное; почему; что отслеживать дальше. "
        "Поле verification_tier=RESEARCH означает, что событие нельзя подавать как подтвержденный факт: "
        "для него action_code должен быть RESEARCH, а текст должен прямо указывать, что требуется проверка. "
        "Также выбери один служебный статус: NO_ACTION, HOLD, WATCH или RESEARCH. "
        "NO_ACTION — событие не меняет инвестиционный тезис и не требует наблюдения; "
        "HOLD — событие относится к уже имеющейся позиции, но оснований менять ее нет; "
        "WATCH — есть понятное условие, за которым нужно наблюдать; "
        "RESEARCH — событие важно, но требует проверки параметров или независимого подтверждения. "
        "Не используй BUY или SELL. Направление влияния — не прогноз цены и не команда купить или продать. "
        "Каждое текстовое поле — максимум 130 символов. Сохрани исходный index.\n\n"
        + json.dumps(input_events, ensure_ascii=False)
    )

    schema = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "index": {"type": "INTEGER"},
                "title_ru": {"type": "STRING"},
                "what_happened_ru": {"type": "STRING"},
                "relevance_ru": {"type": "STRING"},
                "impact_label": {
                    "type": "STRING",
                    "enum": ["Положительное", "Отрицательное", "Смешанное", "Неясное"],
                },
                "impact_reason_ru": {"type": "STRING"},
                "watch_ru": {"type": "STRING"},
                "action_code": {
                    "type": "STRING",
                    "enum": ["NO_ACTION", "HOLD", "WATCH", "RESEARCH"],
                },
                "action_reason_ru": {"type": "STRING"},
            },
            "required": [
                "index",
                "title_ru",
                "what_happened_ru",
                "relevance_ru",
                "impact_label",
                "impact_reason_ru",
                "watch_ru",
                "action_code",
                "action_reason_ru",
            ],
        },
    }

    request_payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2200,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }

    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={
                "x-goog-api-key": GEMINI_API_KEY,
                "Content-Type": "application/json",
            },
            json=request_payload,
            timeout=GEMINI_TIMEOUT,
        )
        response.raise_for_status()
        raw = json.loads(extract_gemini_text(response.json()))
        if not isinstance(raw, list):
            raise RuntimeError("Gemini JSON is not a list")

        by_index = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(selected):
                by_index[index] = {
                    "index": index,
                    "title_ru": trim_text(item.get("title_ru", ""), 100),
                    "what_happened_ru": trim_text(item.get("what_happened_ru", ""), 140),
                    "relevance_ru": trim_text(item.get("relevance_ru", ""), 130),
                    "impact_label": item.get("impact_label", "Неясное"),
                    "impact_reason_ru": trim_text(item.get("impact_reason_ru", ""), 130),
                    "watch_ru": trim_text(item.get("watch_ru", ""), 110),
                    "action_code": item.get("action_code", "RESEARCH"),
                    "action_reason_ru": trim_text(item.get("action_reason_ru", ""), 120),
                }

        result = []
        for index, backup in enumerate(fallback):
            candidate = by_index.get(index)
            if not candidate or not valid_russian_analysis(candidate, selected[index]):
                chosen = backup
            else:
                chosen = candidate

            if selected[index].get("display_tier") == "RESEARCH":
                chosen["action_code"] = "RESEARCH"
                if "провер" not in chosen.get("action_reason_ru", "").lower():
                    chosen["action_reason_ru"] = (
                        "Источник или независимость сообщения недостаточны; параметры события нужно проверить."
                    )
            result.append(chosen)

        return result, f"{GEMINI_MODEL}: русский разбор выполнен"

    except Exception as error:
        print(f"Gemini analysis failed: {error}")
        return fallback, f"Gemini недоступен — резервный русский шаблон ({clean_text(str(error))[:90]})"


def build_report(
    base_working,
    radar_working,
    failures,
    stats,
    events,
    event_analyses,
    gemini_status,
    elapsed_seconds,
    account_positions,
    watchlist_tickers,
    coverage_stats,
):
    action_label, action_reason = overall_action(event_analyses)

    fixed_before_events = [
        "⚠️ ВРЕМЕННЫЙ ДИАГНОСТИЧЕСКИЙ ДАЙДЖЕСТ",
        f"Версия: {VERSION}",
        "",
        "📋 Что делать сегодня",
        f"{action_label}. {action_reason}",
    ]
    fixed_after_events = []
    fixed_after_events.extend(
        portfolio_lines(
            account_positions,
            watchlist_tickers,
            events,
            event_analyses,
        )
    )
    fixed_after_events.extend(budget_lines())
    fixed_after_events.extend(opportunity_lines())
    fixed_after_events.extend(
        [
            "",
            "🧭 Полнота данных",
            (
                f"• RSS {len(base_working)}/{len(BASE_FEEDS)}; "
                f"радар {len(radar_working)}/3; ошибок {len(failures)}."
            ),
            (
                f"• Отсеяно: рекламных PR {stats['filtered_pr']}; "
                f"низкокачественных источников {stats['filtered_low_quality']}; "
                f"мнений/кликбейта {stats['filtered_opinion']}."
            ),
            (
                f"• После фильтра: публикаций {coverage_stats['articles_after_quality']}; "
                f"событий {coverage_stats['clusters_total']}; "
                f"подтвержденных {coverage_stats['confirmed_total']}; "
                f"требуют проверки {coverage_stats['research_total']}."
            ),
            f"• Обработка текста: {gemini_status}.",
            f"• Сбор и анализ: {elapsed_seconds:.1f} сек.",
        ]
    )

    if failures:
        fixed_after_events.extend(["", "❌ Не сработали:"])
        for failure in failures[:3]:
            fixed_after_events.append(
                f"• {failure['name']}: {failure['error'][:90]}"
            )

    fixed_after_events.extend(
        [
            "",
            (
                "⚠️ Информационный фон не является прогнозом цены. "
                "Котировки и фундаментальные данные еще не подключены, "
                "поэтому команд покупать или продавать нет."
            ),
            f"🕒 Создано: {now_kz().strftime('%H:%M:%S')} KZ",
        ]
    )

    event_lines = ["", "🔄 Что изменилось"]
    confirmed_indices = [
        index for index, event in enumerate(events)
        if event.get("display_tier") == "CONFIRMED"
    ]
    research_indices = [
        index for index, event in enumerate(events)
        if event.get("display_tier") == "RESEARCH"
    ]

    if not confirmed_indices and not research_indices:
        event_lines.append(
            "Подтвержденных изменений и сообщений, требующих проверки, не найдено."
        )

    def event_block(index, research=False):
        event = events[index]
        analysis = event_analyses[index]
        newest_kz = event["newest"].astimezone(KZ_TIMEZONE)
        prefix = "🟡 Требует проверки" if research else "•"
        return [
            "",
            f"{prefix} {analysis['title_ru']}",
            f"  Что произошло: {analysis['what_happened_ru']}",
            f"  Для портфеля: {analysis['relevance_ru']}",
            f"  Влияние: {analysis['impact_label']} — {analysis['impact_reason_ru']}",
            f"  Контроль: {analysis['watch_ru']}",
            (
                f"  Статус: {ACTION_LABELS_RU[analysis['action_code']]}. "
                f"{analysis['action_reason_ru']}"
            ),
            (
                f"  Проверка: {event['confirmation']['label']}; "
                f"источники: {', '.join(source_groups(event)[:4])}; "
                f"{newest_kz.strftime('%d.%m %H:%M')} KZ."
            ),
        ]

    # Mandatory sections are preserved. Events are added only while the whole
    # message remains inside the Telegram safety limit.
    for index in confirmed_indices:
        candidate = event_lines + event_block(index, research=False)
        whole = fixed_before_events + candidate + fixed_after_events
        if len("\n".join(whole)) <= TELEGRAM_SAFE_LIMIT:
            event_lines = candidate
        else:
            break

    for index in research_indices:
        candidate = event_lines + event_block(index, research=True)
        whole = fixed_before_events + candidate + fixed_after_events
        if len("\n".join(whole)) <= TELEGRAM_SAFE_LIMIT:
            event_lines = candidate
        else:
            break

    shown_events = sum(
        1 for line in event_lines
        if line.startswith("• ") or line.startswith("🟡 Требует проверки ")
    )
    hidden_events = len(events) - shown_events
    if hidden_events > 0:
        notice = (
            f"Еще отобрано событий: {hidden_events}. Они не скрыты как несуществующие: "
            "количество отражено в блоке полноты данных, но подробности не помещены в одно сообщение."
        )
        candidate = event_lines + ["", notice]
        whole = fixed_before_events + candidate + fixed_after_events
        if len("\n".join(whole)) <= TELEGRAM_SAFE_LIMIT:
            event_lines = candidate

    lines = fixed_before_events + event_lines + fixed_after_events
    text = "\n".join(lines)

    if len(text) > TELEGRAM_SAFE_LIMIT:
        raise RuntimeError(
            f"Telegram report exceeded safe limit: {len(text)}"
        )

    required_sections = [
        "📋 Что делать сегодня",
        "🔄 Что изменилось",
        "📊 Влияние на мои инвестиции",
        "• Freedom",
        "• Paidax",
        "• Watch List",
        "💰 Инвестиционный бюджет",
        "🔎 Новые возможности",
        "🧭 Полнота данных",
    ]
    missing = [section for section in required_sections if section not in text]
    if missing:
        raise RuntimeError(
            "Release contract broken; missing sections: " + ", ".join(missing)
        )

    for event in events:
        for article in event.get("articles", []):
            raw_title = clean_text(article.get("title", ""))
            if raw_title and len(raw_title) >= 20 and raw_title in text:
                raise RuntimeError(
                    "Raw source title leaked into Telegram report"
                )

    return text

def send_to_telegram(text):
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True},
        timeout=TELEGRAM_TIMEOUT,
    )
    response.raise_for_status()
    print("Telegram sent")


def run_release_gate_or_stop():
    gate_path = Path(__file__).with_name("test_release_gate.py")
    requirements_path = Path(__file__).with_name("PROJECT_REQUIREMENTS.json")

    if not gate_path.exists():
        raise RuntimeError(
            "Release gate is missing: test_release_gate.py"
        )
    if not requirements_path.exists():
        raise RuntimeError(
            "Release requirements are missing: PROJECT_REQUIREMENTS.json"
        )

    environment = os.environ.copy()
    environment["RELEASE_GATE_TARGET"] = str(Path(__file__).resolve())
    result = subprocess.run(
        [sys.executable, str(gate_path)],
        cwd=str(Path(__file__).resolve().parent),
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr)
        raise RuntimeError(
            "RELEASE GATE FAILED. Digest execution is blocked."
        )


def main():
    started = time.monotonic()
    print(f"START {VERSION} {now_kz().isoformat()}")

    portfolio_data = load_json_file("portfolio.json")
    watchlist_data = load_json_file("watchlist.json")
    entities = build_user_entities(portfolio_data, watchlist_data)
    ticker_locations = collect_ticker_locations(portfolio_data, watchlist_data)

    articles, base_working, radar_working, failures, stats = collect_sources(entities)
    articles = deduplicate_articles(articles)
    articles, quality_stats = quality_filter_articles(articles)
    stats.update(quality_stats)
    clusters = cluster_articles(articles, entities)
    confirmed_events, research_events = classify_event_buckets(clusters)
    events = select_events_for_report(
        confirmed_events,
        research_events,
    )
    account_positions = extract_account_positions(portfolio_data)
    watchlist_tickers = extract_watchlist_positions(watchlist_data)
    coverage_stats = {
        "articles_after_quality": len(articles),
        "clusters_total": len(clusters),
        "confirmed_total": len(confirmed_events),
        "research_total": len(research_events),
    }

    event_analyses, gemini_status = analyze_events_in_russian(
        events,
        ticker_locations,
    )
    elapsed = time.monotonic() - started

    print("BASE:", *base_working, sep="\n  ")
    print("RADAR:", *radar_working, sep="\n  ")
    print("FAILURES:", *[f"{x['name']}: {x['error']}" for x in failures], sep="\n  ")
    print(f"GEMINI: {gemini_status}")
    print(f"EVENTS SELECTED: {len(events)}; CONFIRMED TOTAL: {len(confirmed_events)}; RESEARCH TOTAL: {len(research_events)}")
    for index, event in enumerate(events):
        analysis_title = (
            event_analyses[index]["title_ru"]
            if index < len(event_analyses)
            else event["primary_subject"]
        )
        print(
            f"  {event['primary_subject']} | {event['event_type']} | "
            f"{event['score']} | {','.join(source_groups(event))} | {analysis_title}"
        )

    report = build_report(
        base_working,
        radar_working,
        failures,
        stats,
        events,
        event_analyses,
        gemini_status,
        elapsed,
        account_positions,
        watchlist_tickers,
        coverage_stats,
    )
    print(report)
    send_to_telegram(report)
    print(
        f"FINISH {VERSION} in {time.monotonic() - started:.1f}s "
        f"at {now_kz().isoformat()}"
    )


if __name__ == "__main__":
    run_release_gate_or_stop()
    main()
