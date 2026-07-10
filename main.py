import os
import re
import json
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlparse

import feedparser
import requests

VERSION = "TEMP-SAFETY-v2.3"
KZ_TIMEZONE = timezone(timedelta(hours=5))
LOOKBACK_HOURS = 48

RSS_TIMEOUT = 15
GDELT_TIMEOUT = 25
GDELT_MIN_INTERVAL_SECONDS = 6
GDELT_MAX_RECORDS = 250
GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"

MAX_EVENTS_IN_TELEGRAM = 6
TELEGRAM_SAFE_LIMIT = 3600

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

# Полные названия важнее коротких тикеров: это устраняет ложные совпадения.
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

# Источники для отдельного приоритетного поиска.
PRIORITY_MEDIA_DOMAINS = [
    "reuters.com",
    "bloomberg.com",
    "apnews.com",
    "ft.com",
    "wsj.com",
    "cnbc.com",
    "marketwatch.com",
]

TOPIC_QUERY = (
    '("semiconductor" OR "chipmakers" OR "HBM" OR "AI chips" '
    'OR "uranium" OR "nuclear power" OR "oil prices" OR "crude oil" '
    'OR "gold prices" OR "silver prices" OR "bitcoin" '
    'OR "Federal Reserve" OR "US inflation" OR "US jobs report")'
)

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
        r"\bshare sale\b", r"\bmarket debut\b", r"\bNasdaq debut\b",
        r"\bring the Nasdaq bell\b", r"\bhit the U\.?S\.? market\b",
    ],
    "capital_return": [
        r"\bdividend\b", r"\bbuyback\b", r"\bshare repurchase\b",
    ],
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
        r"\bcontract award\b", r"\bawarded a contract\b",
        r"\bmajor contract\b",
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
    "market_move": 18,
    "other": 5,
}

# Комментарии не должны становиться главным заголовком фактического события.
OPINION_PATTERNS = [
    r"\bJim Cramer\b",
    r"\bwhat I think\b",
    r"\bmy take\b",
    r"\bstands on\b",
    r"\bshould you buy\b",
    r"\bwhy I am buying\b",
    r"\bdumping all my\b",
    r"\brating upgrade\b",
    r"\brating downgrade\b",
    r"\banalyst says\b",
]

OFFICIAL_DOMAINS = {
    "sec.gov", "federalreserve.gov", "bls.gov", "bea.gov",
    "eia.gov", "treasury.gov", "nasdaqtrader.com", "fss.or.kr",
    "krx.co.kr", "nationalbank.kz", "kase.kz", "aix.kz",
    "iaea.org", "nrc.gov",
}

AUTHORITATIVE_MEDIA = {
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

AGGREGATOR_DOMAINS = {
    "investing.com", "finance.yahoo.com", "yahoo.com", "msn.com",
    "news.google.com", "seekingalpha.com", "benzinga.com",
}

PRESS_RELEASE_DOMAINS = {
    "prnewswire.com", "globenewswire.com", "businesswire.com",
}

MULTIPART_PUBLIC_SUFFIXES = {
    "co.kr", "co.uk", "com.sg", "com.au", "co.jp",
    "com.hk", "com.my", "co.nz", "com.br", "co.in",
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for",
    "with", "from", "by", "after", "as", "at", "is", "are", "says",
    "said", "more", "than", "its", "this", "that", "will", "new",
    "us", "u", "s",
}

STRONG_CLUSTER_TYPES = {
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
}


def now_kz():
    return datetime.now(timezone.utc).astimezone(KZ_TIMEZONE)


def clean_text(value):
    text = unescape(value or "")
    return " ".join(
        text.replace("\n", " ").replace("\r", " ").split()
    ).strip()


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

    if any(
        rd == item or domain.endswith("." + item)
        for item in OFFICIAL_DOMAINS
    ):
        return {
            "group": "OFFICIAL",
            "trust": 100,
            "tier": 0,
            "kind": "official",
            "counts_as_independent": True,
        }

    if rd in AUTHORITATIVE_MEDIA:
        group, trust, tier = AUTHORITATIVE_MEDIA[rd]
        return {
            "group": group,
            "trust": trust,
            "tier": tier,
            "kind": "authoritative_media",
            "counts_as_independent": True,
        }

    if rd in PRESS_RELEASE_DOMAINS or source_name in PRESS_RELEASE_SOURCES:
        return {
            "group": "ISSUER_RELEASE",
            "trust": 70,
            "tier": 4,
            "kind": "issuer_statement",
            "counts_as_independent": False,
        }

    if rd in AGGREGATOR_DOMAINS:
        return {
            "group": "AGGREGATOR",
            "trust": 50,
            "tier": 5,
            "kind": "aggregator",
            "counts_as_independent": False,
        }

    return {
        "group": f"MEDIA:{rd or source_name.lower()}",
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


def parse_gdelt_datetime(value):
    if not value:
        return None

    for fmt in (
        "%Y%m%dT%H%M%SZ",
        "%Y%m%d%H%M%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(str(value), fmt).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            pass

    return None


def normalize_tokens(text):
    words = re.findall(
        r"[a-zA-Zа-яА-ЯёЁ0-9]+",
        clean_text(text).lower(),
    )
    return {
        word for word in words
        if len(word) > 2 and word not in STOPWORDS
    }


def title_similarity(left, right):
    a = normalize_tokens(left)
    b = normalize_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def classify_event_type(text):
    for event_type, patterns in EVENT_PATTERNS.items():
        if any(
            re.search(pattern, text, flags=re.IGNORECASE)
            for pattern in patterns
        ):
            return event_type
    return "other"


def is_opinion_title(title):
    return any(
        re.search(pattern, title, flags=re.IGNORECASE)
        for pattern in OPINION_PATTERNS
    )


def is_material_press_release(title, summary):
    return classify_event_type(f"{title} {summary}") != "other"


def build_user_entities(portfolio_data, watchlist_data):
    tickers = set()

    for positions in portfolio_data.values():
        if isinstance(positions, dict):
            tickers.update(
                str(ticker).upper().strip()
                for ticker in positions
                if str(ticker).strip()
            )

    for item in watchlist_data.get("watchlist", []):
        if isinstance(item, dict):
            ticker = str(item.get("ticker", "")).upper().strip()
            if ticker:
                tickers.add(ticker)

    # SKHY остается в радаре, пока пользователь ведет отдельную задачу
    # по этому размещению.
    tickers.add("SKHY")

    entities = {}
    for ticker in sorted(tickers):
        aliases = ENTITY_ALIASES.get(ticker, [])
        if aliases:
            entities[ticker] = list(dict.fromkeys(aliases))

    return entities


def make_entity_query(user_entities):
    phrases = []
    for aliases in user_entities.values():
        if aliases:
            phrases.append(f'"{aliases[0]}"')
    return "(" + " OR ".join(phrases) + ")"


def fetch_one_rss(source_name, feed_url, cutoff):
    response = requests.get(
        feed_url,
        headers={"User-Agent": "Mozilla/5.0 InvestmentAssistant/2.3"},
        timeout=RSS_TIMEOUT,
    )
    response.raise_for_status()

    feed = feedparser.parse(response.content)
    if getattr(feed, "bozo", False) and not feed.entries:
        raise RuntimeError(
            f"RSS parse error: "
            f"{getattr(feed, 'bozo_exception', 'unknown')}"
        )

    articles = []
    raw_count = 0
    filtered_pr = 0

    for entry in feed.entries:
        title = clean_text(getattr(entry, "title", ""))
        summary = clean_text(getattr(entry, "summary", ""))
        link = clean_text(getattr(entry, "link", ""))
        published_at = parse_entry_datetime(entry)

        if not title or published_at is None or published_at < cutoff:
            continue

        raw_count += 1

        if source_name in PRESS_RELEASE_SOURCES:
            if not is_material_press_release(title, summary):
                filtered_pr += 1
                continue

        articles.append(
            {
                "title": title,
                "summary": summary,
                "url": link,
                "domain": domain_from_url(link),
                "published_at": published_at,
                "source_name": source_name,
                "discovery_channel": "RSS",
            }
        )

    return {
        "source": source_name,
        "articles": articles,
        "raw_count": raw_count,
        "filtered_pr": filtered_pr,
    }


def collect_rss():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    articles = []
    working = []
    failed = []
    stats = {"raw_rss": 0, "filtered_pr": 0}

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(fetch_one_rss, name, url, cutoff): name
            for name, url in RSS_FEEDS
        }

        for future in as_completed(futures):
            source_name = futures[future]
            try:
                result = future.result()
                articles.extend(result["articles"])
                stats["raw_rss"] += result["raw_count"]
                stats["filtered_pr"] += result["filtered_pr"]
                working.append(
                    f"{source_name}: {len(result['articles'])}"
                )
            except Exception as error:
                failed.append(
                    f"{source_name}: {clean_text(str(error))[:160]}"
                )

    working.sort()
    failed.sort()
    return articles, working, failed, stats


class GdeltClient:
    def __init__(self):
        self.last_request_at = 0.0

    def _wait_for_interval(self):
        elapsed = time.monotonic() - self.last_request_at
        remaining = GDELT_MIN_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def search(self, query, label, sort_mode="datedesc"):
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "timespan": f"{LOOKBACK_HOURS}h",
            "maxrecords": str(GDELT_MAX_RECORDS),
            "sort": sort_mode,
        }

        last_error = None

        for attempt in range(1, 3):
            self._wait_for_interval()

            response = requests.get(
                GDELT_ENDPOINT,
                params=params,
                headers={"User-Agent": "InvestmentAssistant/2.3"},
                timeout=GDELT_TIMEOUT,
            )
            self.last_request_at = time.monotonic()

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait_seconds = int(retry_after)
                except (TypeError, ValueError):
                    wait_seconds = 20

                last_error = RuntimeError(
                    f"429 Too Many Requests, retry after {wait_seconds}s"
                )
                if attempt == 1:
                    time.sleep(min(max(wait_seconds, 10), 30))
                    continue

            try:
                response.raise_for_status()
                payload = response.json()
            except Exception as error:
                last_error = error
                if attempt == 1:
                    time.sleep(10)
                    continue
                break

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
                        "domain": (
                            clean_text(item.get("domain", ""))
                            or domain_from_url(url)
                        ),
                        "published_at": parse_gdelt_datetime(
                            item.get("seendate")
                        ),
                        "source_name": (
                            clean_text(item.get("domain", ""))
                            or "GDELT"
                        ),
                        "discovery_channel": f"GDELT:{label}",
                    }
                )

            return articles

        raise RuntimeError(f"{label}: {last_error}")


def collect_gdelt(user_entities):
    client = GdeltClient()
    articles = []
    working = []
    failed = []

    entity_query = make_entity_query(user_entities)

    domain_query = "(" + " OR ".join(
        f"domainis:{domain}" for domain in PRIORITY_MEDIA_DOMAINS
    ) + ")"

    searches = [
        (
            f"{entity_query} {domain_query}",
            "PRIORITY_MEDIA",
            "datedesc",
        ),
        (
            entity_query,
            "DIRECT_ENTITIES",
            "hybridrel",
        ),
        (
            TOPIC_QUERY,
            "MARKET_TOPICS",
            "datedesc",
        ),
    ]

    for query, label, sort_mode in searches:
        try:
            found = client.search(query, label, sort_mode)
            articles.extend(found)
            working.append(f"{label}: {len(found)}")
        except Exception as error:
            failed.append(clean_text(str(error))[:180])

    return articles, working, failed


def infer_subjects(article, user_entities):
    title = clean_text(article.get("title", ""))
    title_lower = title.lower()
    matches = []

    for ticker, aliases in user_entities.items():
        best_alias = None
        for alias in aliases:
            pattern = r"(?<!\w)" + re.escape(alias.lower()) + r"(?!\w)"
            if re.search(pattern, title_lower):
                if best_alias is None or len(alias) > len(best_alias):
                    best_alias = alias

        if best_alias:
            matches.append((ticker, best_alias))

    if matches:
        # Самое длинное полное название считается главным объектом.
        matches.sort(key=lambda item: len(item[1]), reverse=True)
        return [ticker for ticker, _alias in matches], True

    topic_checks = {
        "SEMICONDUCTORS": [
            "semiconductor", "chipmaker", "hbm", "ai chip",
        ],
        "ENERGY": ["oil", "crude", "opec", "iran"],
        "URANIUM": ["uranium", "nuclear"],
        "PRECIOUS_METALS": ["gold", "silver"],
        "CRYPTO": ["bitcoin", "crypto"],
        "US_MARKET": [
            "federal reserve", "inflation", "jobs report",
            "nasdaq", "s&p 500",
        ],
    }

    for topic, terms in topic_checks.items():
        if any(term in title_lower for term in terms):
            return [topic], False

    return ["GENERAL"], False


def deduplicate_articles(articles):
    seen_urls = set()
    result = []

    for article in articles:
        url = clean_text(article.get("url", "")).lower()
        title = clean_text(article.get("title", "")).lower()

        raw = f"{url}|{title}".encode("utf-8", errors="ignore")
        key = hashlib.sha256(raw).hexdigest()

        if key in seen_urls:
            continue

        seen_urls.add(key)
        result.append(article)

    return result


def cluster_articles(articles, user_entities):
    clusters = []

    valid_articles = [
        article for article in articles
        if article.get("published_at") is not None
    ]
    valid_articles.sort(
        key=lambda item: item["published_at"],
        reverse=True,
    )

    for article in valid_articles:
        subjects, direct = infer_subjects(article, user_entities)
        primary_subject = subjects[0]
        event_type = classify_event_type(
            f"{article.get('title', '')} "
            f"{article.get('summary', '')}"
        )
        day = article["published_at"].astimezone(
            KZ_TIMEZONE
        ).date().isoformat()

        article["subjects"] = subjects
        article["primary_subject"] = primary_subject
        article["direct_user_relevance"] = direct
        article["event_type"] = event_type
        article["source_profile"] = source_profile(
            article.get("domain", ""),
            article.get("source_name", ""),
        )
        article["is_opinion"] = is_opinion_title(
            article.get("title", "")
        )

        matched = None

        for cluster in clusters:
            if cluster["primary_subject"] != primary_subject:
                continue
            if cluster["event_type"] != event_type:
                continue
            if cluster["day"] != day:
                continue

            if event_type in STRONG_CLUSTER_TYPES:
                matched = cluster
                break

            if title_similarity(
                cluster["seed_title"],
                article["title"],
            ) >= 0.30:
                matched = cluster
                break

        if matched is None:
            clusters.append(
                {
                    "primary_subject": primary_subject,
                    "subjects": set(subjects),
                    "direct_user_relevance": direct,
                    "event_type": event_type,
                    "day": day,
                    "seed_title": article["title"],
                    "articles": [article],
                }
            )
        else:
            matched["articles"].append(article)
            matched["subjects"].update(subjects)
            matched["direct_user_relevance"] = (
                matched["direct_user_relevance"] or direct
            )

    return clusters


def confirmation_status(cluster):
    independent_groups = set()
    official_present = False
    best_trust = 0

    for article in cluster["articles"]:
        profile = article["source_profile"]
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
    def rank(article):
        profile = article["source_profile"]
        return (
            1 if article["is_opinion"] else 0,
            profile["tier"],
            -profile["trust"],
            -article["published_at"].timestamp(),
        )

    return sorted(cluster["articles"], key=rank)[0]


def importance_score(cluster, confirmation):
    score = 0

    if cluster["direct_user_relevance"]:
        score += 45
    elif cluster["primary_subject"] != "GENERAL":
        score += 18

    score += EVENT_WEIGHTS.get(cluster["event_type"], 5)

    if confirmation["code"] == "OFFICIAL_CONFIRMED":
        score += 20
    elif confirmation["code"] == "MULTI_SOURCE_CONFIRMED":
        score += 18
    elif confirmation["code"] == "RELIABLE_SINGLE_SOURCE":
        score += 15
    elif confirmation["code"] == "REPEATED_NOT_INDEPENDENT":
        score += 4

    newest = max(
        article["published_at"]
        for article in cluster["articles"]
    )
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
        representative = choose_representative_article(cluster)

        include = False

        # Прямое событие по портфелю/watchlist с сильным типом
        # показывается даже по одному Reuters/Bloomberg/AP/FT/WSJ.
        if (
            cluster["direct_user_relevance"]
            and cluster["event_type"] in STRONG_CLUSTER_TYPES
            and score >= 60
        ):
            include = True
        elif score >= 72:
            include = True
        elif (
            confirmation["code"] in {
                "OFFICIAL_CONFIRMED",
                "MULTI_SOURCE_CONFIRMED",
                "RELIABLE_SINGLE_SOURCE",
            }
            and score >= 60
        ):
            include = True

        # Обычное мнение без нового фактического события
        # не должно занимать основной блок.
        if (
            representative["is_opinion"]
            and cluster["event_type"] == "other"
        ):
            include = False

        if include:
            newest = max(
                article["published_at"]
                for article in cluster["articles"]
            )
            results.append(
                {
                    **cluster,
                    "confirmation": confirmation,
                    "score": score,
                    "newest": newest,
                    "representative": representative,
                }
            )

    results.sort(
        key=lambda item: (
            item["direct_user_relevance"],
            item["score"],
            item["newest"],
        ),
        reverse=True,
    )
    return results


def source_groups(cluster):
    groups = []

    for article in cluster["articles"]:
        group = article["source_profile"]["group"]
        if group not in groups:
            groups.append(group)

    return groups


def compact_subject(event):
    subjects = list(event["subjects"])
    primary = event["primary_subject"]
    others = [item for item in subjects if item != primary]

    if not others:
        return primary

    return f"{primary}; связано: {', '.join(sorted(others)[:2])}"


def build_report(rss_status, gdelt_status, stats, events):
    rss_working, rss_failed = rss_status
    gdelt_working, gdelt_failed = gdelt_status

    lines = [
        "⚠️ ВРЕМЕННЫЙ ДИАГНОСТИЧЕСКИЙ ДАЙДЖЕСТ",
        f"Версия: {VERSION}",
        "",
        (
            f"📡 RSS {len(rss_working)}/{len(RSS_FEEDS)}; "
            f"GDELT {len(gdelt_working)}/3; "
            f"ошибок {len(rss_failed) + len(gdelt_failed)}; "
            f"рекламных PR отсеяно {stats['filtered_pr']}."
        ),
        "",
        "🚨 Важные события",
    ]

    if not events:
        lines.append(
            "События с достаточной важностью в доступных источниках "
            "не обнаружены. Полнота рынка пока не гарантируется."
        )
    else:
        shown = 0

        for event in events:
            if shown >= MAX_EVENTS_IN_TELEGRAM:
                break

            representative = event["representative"]
            newest_kz = event["newest"].astimezone(KZ_TIMEZONE)
            groups = source_groups(event)
            title = representative["title"]

            block = [
                "",
                f"• {compact_subject(event)} — {title}",
                (
                    f"  Важность {event['score']}/100; "
                    f"{event['confirmation']['label']}."
                ),
                (
                    f"  Группы: {', '.join(groups[:4])}; "
                    f"публикаций в событии: {len(event['articles'])}; "
                    f"{newest_kz.strftime('%d.%m %H:%M')} KZ."
                ),
            ]

            candidate = "\n".join(lines + block)
            if len(candidate) > TELEGRAM_SAFE_LIMIT:
                break

            lines.extend(block)
            shown += 1

        remaining = len(events) - shown
        if remaining > 0:
            lines.extend(
                [
                    "",
                    f"Еще важных событий: {remaining}. "
                    "Они записаны в логе Actions, а не обрезаны посередине.",
                ]
            )

    lines.extend(
        [
            "",
            "⚠️ Котировки и фундаментальные данные еще не подключены. "
            "Эта версия выявляет события, но не дает команд покупать "
            "или продавать.",
            f"🕒 Создано: {now_kz().strftime('%H:%M:%S')} KZ",
        ]
    )

    text = "\n".join(lines)

    if len(text) > TELEGRAM_SAFE_LIMIT:
        raise RuntimeError(
            f"Telegram report exceeded safe limit: {len(text)}"
        )

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
            response = requests.post(
                url,
                json=payload,
                timeout=20,
            )
            response.raise_for_status()
            print(f"Telegram sent, attempt {attempt}")
            return
        except Exception as error:
            last_error = error
            print(
                f"Telegram error, attempt {attempt}: {error}"
            )

    raise RuntimeError(
        f"Telegram delivery failed: {last_error}"
    )


def print_diagnostics(
    rss_working,
    rss_failed,
    gdelt_working,
    gdelt_failed,
    events,
):
    print("RSS WORKING:")
    for item in rss_working:
        print(f"  {item}")

    print("RSS FAILED:")
    for item in rss_failed:
        print(f"  {item}")

    print("GDELT WORKING:")
    for item in gdelt_working:
        print(f"  {item}")

    print("GDELT FAILED:")
    for item in gdelt_failed:
        print(f"  {item}")

    print(f"EVENTS SELECTED: {len(events)}")
    for event in events:
        print(
            f"  {event['primary_subject']} | "
            f"{event['event_type']} | "
            f"{event['score']} | "
            f"{event['representative']['title']}"
        )


def main():
    print(f"START {VERSION} {now_kz().isoformat()}")

    portfolio_data = load_json_file("portfolio.json")
    watchlist_data = load_json_file("watchlist.json")
    user_entities = build_user_entities(
        portfolio_data,
        watchlist_data,
    )

    rss_articles, rss_working, rss_failed, stats = collect_rss()
    gdelt_articles, gdelt_working, gdelt_failed = collect_gdelt(
        user_entities
    )

    articles = deduplicate_articles(
        rss_articles + gdelt_articles
    )
    clusters = cluster_articles(articles, user_entities)
    events = score_and_filter_clusters(clusters)

    print_diagnostics(
        rss_working,
        rss_failed,
        gdelt_working,
        gdelt_failed,
        events,
    )

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
