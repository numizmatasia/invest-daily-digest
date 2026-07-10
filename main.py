import os
import re
import json
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlencode, urlparse

import feedparser
import requests

VERSION = "TEMP-SAFETY-v2.4"
KZ_TIMEZONE = timezone(timedelta(hours=5))
LOOKBACK_HOURS = 48
REQUEST_TIMEOUT = 12
TELEGRAM_TIMEOUT = 20
MAX_EVENTS_IN_TELEGRAM = 6
TELEGRAM_SAFE_LIMIT = 3600

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

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
    r"\banalyst says\b",
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
PRESS_RELEASE_DOMAINS = {"prnewswire.com", "globenewswire.com", "businesswire.com"}
MULTIPART_PUBLIC_SUFFIXES = {"co.kr", "co.uk", "com.sg", "com.au", "co.jp", "com.hk", "com.my", "co.nz", "com.br", "co.in"}
STOPWORDS = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "from", "by", "after", "as", "at", "is", "are", "says", "said", "more", "than", "its", "this", "that", "will", "new", "us", "u", "s"}
STRONG_CLUSTER_TYPES = {"earnings", "guidance", "merger_acquisition", "capital_markets", "capital_return", "distress", "regulatory", "legal_sanctions", "management", "operations"}


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
        return {"group": "OFFICIAL", "trust": 100, "tier": 0, "kind": "official", "counts_as_independent": True}

    if name in AUTHORITATIVE_MEDIA_NAMES:
        group, trust, tier = AUTHORITATIVE_MEDIA_NAMES[name]
        return {"group": group, "trust": trust, "tier": tier, "kind": "authoritative_media", "counts_as_independent": True}

    if rd in AUTHORITATIVE_MEDIA_DOMAINS:
        group, trust, tier = AUTHORITATIVE_MEDIA_DOMAINS[rd]
        return {"group": group, "trust": trust, "tier": tier, "kind": "authoritative_media", "counts_as_independent": True}

    if rd in PRESS_RELEASE_DOMAINS or source_name in PRESS_RELEASE_SOURCES:
        return {"group": "ISSUER_RELEASE", "trust": 70, "tier": 4, "kind": "issuer_statement", "counts_as_independent": False}

    if rd in AGGREGATOR_DOMAINS or name in AGGREGATOR_NAMES:
        return {"group": "AGGREGATOR", "trust": 50, "tier": 5, "kind": "aggregator", "counts_as_independent": False}

    return {"group": f"MEDIA:{rd or name or 'unknown'}", "trust": 62, "tier": 4, "kind": "other_media", "counts_as_independent": False}


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
    for positions in portfolio_data.values():
        if isinstance(positions, dict):
            tickers.update(str(ticker).upper().strip() for ticker in positions if str(ticker).strip())
    for item in watchlist_data.get("watchlist", []):
        if isinstance(item, dict):
            ticker = str(item.get("ticker", "")).upper().strip()
            if ticker:
                tickers.add(ticker)
    tickers.add("SKHY")
    return {ticker: list(dict.fromkeys(ENTITY_ALIASES[ticker])) for ticker in sorted(tickers) if ticker in ENTITY_ALIASES}


def google_news_url(query):
    return f"{GOOGLE_NEWS_ENDPOINT}?{urlencode({'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})}"


def build_radar_feeds(user_entities):
    primary_names = [aliases[0] for aliases in user_entities.values() if aliases]
    entity_query = "(" + " OR ".join(f'\"{name}\"' for name in primary_names) + ") when:2d"
    return [
        ("Radar: portfolio/watchlist", google_news_url(entity_query), "radar"),
        ("Radar: Reuters", google_news_url(f"{entity_query} source:Reuters"), "radar"),
        ("Radar: market topics", google_news_url(MARKET_RADAR_QUERY), "radar"),
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


def collect_sources(user_entities):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    specs = [(name, url, "base") for name, url in BASE_FEEDS] + build_radar_feeds(user_entities)
    articles, base_working, radar_working, failures = [], [], [], []
    stats = {"raw_base": 0, "raw_radar": 0, "filtered_pr": 0}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_feed, name, url, kind, cutoff): (name, kind) for name, url, kind in specs}
        for future in as_completed(futures):
            name, kind = futures[future]
            try:
                result = future.result()
                articles.extend(result["articles"])
                stats["filtered_pr"] += result["filtered_pr"]
                status = f"{name}: {len(result['articles'])}"
                if kind == "base":
                    base_working.append(status)
                    stats["raw_base"] += result["raw_count"]
                else:
                    radar_working.append(status)
                    stats["raw_radar"] += result["raw_count"]
            except Exception as error:
                failures.append({"name": name, "kind": kind, "error": clean_text(str(error))[:140]})

    return articles, sorted(base_working), sorted(radar_working), sorted(failures, key=lambda x: x["name"]), stats


def normalize_tokens(text):
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", clean_text(text).lower())
    return {word for word in words if len(word) > 2 and word not in STOPWORDS}


def title_similarity(left, right):
    a, b = normalize_tokens(left), normalize_tokens(right)
    return 0.0 if not a or not b else len(a & b) / len(a | b)


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
    groups, official, best_trust = set(), False, 0
    for article in cluster["articles"]:
        profile = article["source_profile"]
        best_trust = max(best_trust, profile["trust"])
        official = official or profile["kind"] == "official"
        if profile["counts_as_independent"]:
            groups.add(profile["group"])
    if official:
        return {"code": "OFFICIAL_CONFIRMED", "label": "официально подтверждено", "independent_count": len(groups), "best_trust": best_trust}
    if len(groups) >= 2:
        return {"code": "MULTI_SOURCE_CONFIRMED", "label": "подтверждено 2+ независимыми источниками", "independent_count": len(groups), "best_trust": best_trust}
    if len(groups) == 1 and best_trust >= 82:
        group = next(iter(groups))
        return {"code": "RELIABLE_SINGLE_SOURCE", "label": f"один надежный источник: {group}", "independent_count": 1, "best_trust": best_trust}
    if len(cluster["articles"]) >= 2:
        return {"code": "REPEATED_NOT_INDEPENDENT", "label": "перепечатки без независимого подтверждения", "independent_count": 0, "best_trust": best_trust}
    return {"code": "UNVERIFIED_SINGLE_SOURCE", "label": "один непроверенный источник", "independent_count": 0, "best_trust": best_trust}


def choose_representative_article(cluster):
    return sorted(cluster["articles"], key=lambda a: (1 if a["is_opinion"] else 0, a["source_profile"]["tier"], -a["source_profile"]["trust"], -a["published_at"].timestamp()))[0]


def importance_score(cluster, confirmation):
    score = 45 if cluster["direct_user_relevance"] else (18 if cluster["primary_subject"] != "GENERAL" else 0)
    score += EVENT_WEIGHTS.get(cluster["event_type"], 5)
    score += {"OFFICIAL_CONFIRMED": 20, "MULTI_SOURCE_CONFIRMED": 18, "RELIABLE_SINGLE_SOURCE": 15, "REPEATED_NOT_INDEPENDENT": 4}.get(confirmation["code"], 0)
    newest = max(a["published_at"] for a in cluster["articles"])
    age_hours = (datetime.now(timezone.utc) - newest.astimezone(timezone.utc)).total_seconds() / 3600
    score += 10 if age_hours <= 12 else (5 if age_hours <= 24 else 0)
    return min(score, 100)


def score_and_filter_clusters(clusters):
    results = []
    for cluster in clusters:
        confirmation = confirmation_status(cluster)
        score = importance_score(cluster, confirmation)
        representative = choose_representative_article(cluster)
        include = (
            cluster["direct_user_relevance"] and cluster["event_type"] in STRONG_CLUSTER_TYPES and score >= 60
        ) or score >= 72 or (
            confirmation["code"] in {"OFFICIAL_CONFIRMED", "MULTI_SOURCE_CONFIRMED", "RELIABLE_SINGLE_SOURCE"} and score >= 60
        )
        if representative["is_opinion"] and cluster["event_type"] == "other":
            include = False
        if include:
            results.append({**cluster, "confirmation": confirmation, "score": score, "newest": max(a["published_at"] for a in cluster["articles"]), "representative": representative})
    return sorted(results, key=lambda x: (x["direct_user_relevance"], x["score"], x["newest"]), reverse=True)


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


def build_report(base_working, radar_working, failures, stats, events, elapsed_seconds):
    lines = [
        "⚠️ ВРЕМЕННЫЙ ДИАГНОСТИЧЕСКИЙ ДАЙДЖЕСТ",
        f"Версия: {VERSION}",
        "",
        f"📡 RSS {len(base_working)}/{len(BASE_FEEDS)}; радар {len(radar_working)}/3; ошибок {len(failures)}; рекламных PR отсеяно {stats['filtered_pr']}.",
        f"⏱ Сбор и анализ: {elapsed_seconds:.1f} сек.",
        "",
        "🚨 Важные события",
    ]

    if not events:
        lines.append("События с достаточной важностью в доступных источниках не обнаружены. Полнота рынка пока не гарантируется.")
    else:
        shown = 0
        for event in events:
            if shown >= MAX_EVENTS_IN_TELEGRAM:
                break
            representative = event["representative"]
            newest_kz = event["newest"].astimezone(KZ_TIMEZONE)
            groups = source_groups(event)
            block = [
                "",
                f"• {compact_subject(event)} — {representative['title']}",
                f"  Важность {event['score']}/100; {event['confirmation']['label']}.",
                f"  Группы: {', '.join(groups[:4])}; публикаций: {len(event['articles'])}; {newest_kz.strftime('%d.%m %H:%M')} KZ.",
            ]
            if len("\n".join(lines + block)) > TELEGRAM_SAFE_LIMIT:
                break
            lines.extend(block)
            shown += 1
        if len(events) > shown:
            lines.extend(["", f"Еще важных событий: {len(events) - shown}. Полный список записан в Actions."])

    if failures:
        lines.extend(["", "❌ Не сработали:"])
        for failure in failures[:3]:
            lines.append(f"• {failure['name']}: {failure['error'][:90]}")

    lines.extend([
        "",
        "⚠️ Котировки и фундаментальные данные еще не подключены. Эта версия выявляет события, но не дает команд покупать или продавать.",
        f"🕒 Создано: {now_kz().strftime('%H:%M:%S')} KZ",
    ])
    text = "\n".join(lines)
    if len(text) > TELEGRAM_SAFE_LIMIT:
        raise RuntimeError(f"Telegram report exceeded safe limit: {len(text)}")
    return text


def send_to_telegram(text):
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True},
        timeout=TELEGRAM_TIMEOUT,
    )
    response.raise_for_status()
    print("Telegram sent")


def main():
    started = time.monotonic()
    print(f"START {VERSION} {now_kz().isoformat()}")

    entities = build_user_entities(load_json_file("portfolio.json"), load_json_file("watchlist.json"))
    articles, base_working, radar_working, failures, stats = collect_sources(entities)
    events = score_and_filter_clusters(cluster_articles(deduplicate_articles(articles), entities))
    elapsed = time.monotonic() - started

    print("BASE:", *base_working, sep="\n  ")
    print("RADAR:", *radar_working, sep="\n  ")
    print("FAILURES:", *[f"{x['name']}: {x['error']}" for x in failures], sep="\n  ")
    print(f"EVENTS SELECTED: {len(events)}")
    for event in events:
        print(f"  {event['primary_subject']} | {event['event_type']} | {event['score']} | {','.join(source_groups(event))} | {event['representative']['title']}")

    report = build_report(base_working, radar_working, failures, stats, events, elapsed)
    print(report)
    send_to_telegram(report)
    print(f"FINISH {VERSION} in {time.monotonic() - started:.1f}s at {now_kz().isoformat()}")


if __name__ == "__main__":
    main()
