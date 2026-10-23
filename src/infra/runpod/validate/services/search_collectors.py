"""
search_collectors.py  (Stage 3 collectors)
==========================================
Replaces the file that held RawEvidenceItem / fetch_macro_indicators /
fetch_community_discussions.  fetch_vertex_search (Vertex AI Search over the curated site
list) now lives here too, so every collector that _handle_validate_search calls is
imported from this one module.

Every public collector returns  list[dict]  (RawEvidenceItem.to_dict()), which is what
_handle_validate_search indexes with item["parameter"], and is RunPod/JSON friendly.

Collectors
----------
fetch_macro_indicators      parameter "macro"   World Bank WDI via DBnomics, fallback: World Bank API
fetch_market_indicators     parameter "market"  self-employed %, labour force, internet users (same engine)
fetch_community_discussions Hacker News text    (pain / demand evidence)
fetch_hn_mention_trend      parameter "demand"  mentions per calendar quarter (time series)
fetch_wikipedia_pageviews   parameter "demand"  monthly pageviews of the best-matching article (time series)
fetch_appstore_reviews      "pain" (1-3 star reviews) + "competition" (app listings)
fetch_vertex_search         the 8 Vertex-backed parameters (legacy names); reports, pricing, regulation

Dependencies: httpx; pycountry (optional, better country resolution);
google-cloud-discoveryengine + src.core.settings (imported lazily, only by fetch_vertex_search)
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import re
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx

try:  # optional
    import pycountry
except ImportError:  # pragma: no cover
    pycountry = None

logger = logging.getLogger(__name__)

UA = "IdeaValidatorBot/0.1 (+contact: set-your-email@example.com)"
BACKOFF_BASE = 1.0  # seconds; tests set this to 0

__all__ = [
    "RawEvidenceItem", "resolve_country",
    "fetch_macro_indicators", "fetch_market_indicators",
    "fetch_community_discussions", "fetch_hn_mention_trend",
    "fetch_wikipedia_pageviews", "fetch_appstore_reviews",
    "fetch_vertex_search",
]

# --------------------------------------------------------------------------- #
# Shared schema + helpers
# --------------------------------------------------------------------------- #


def _utcnow() -> datetime:
    """Naive UTC, same value the old datetime.utcnow() produced (which is deprecated)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RawEvidenceItem:
    """Standardized schema for all scraped evidence before it hits the DB."""

    def __init__(self, parameter: str, source_type: str, source_url: str, raw_content: str,
                 title: str | None = None, metadata: dict[str, Any] | None = None,
                 retrieved_at: datetime | None = None):
        self.parameter = parameter
        self.source_type = source_type
        self.source_url = source_url
        self.raw_content = raw_content
        self.title = title
        self.metadata = metadata or {}
        self.retrieved_at = retrieved_at or _utcnow()

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter, "source_type": self.source_type,
            "source_url": self.source_url, "title": self.title,
            "raw_content": self.raw_content, "metadata": self.metadata,
            "retrieved_at": self.retrieved_at.isoformat(),
        }


def strip_html(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _unique(items: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in items or []:
        s = (s or "").strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def _client(timeout: float = 12.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, headers={"User-Agent": UA}, follow_redirects=True)


async def _get_json(client: httpx.AsyncClient, url: str, params: dict | None = None,
                    retries: int = 3, label: str = "http") -> Any:
    """GET + JSON with backoff on 429/5xx and transport errors. None on failure."""
    for attempt in range(retries):
        try:
            r = await client.get(url, params=params)
            if r.status_code in (429, 500, 502, 503, 504):
                logger.warning("[%s] HTTP %s, retry %d/%d", label, r.status_code, attempt + 1, retries)
                await asyncio.sleep(BACKOFF_BASE * 2 ** attempt)
                continue
            if r.status_code != 200:
                logger.warning("[%s] HTTP %s for %s", label, r.status_code, url)
                return None
            return r.json()
        except (httpx.TransportError, ValueError) as exc:
            logger.warning("[%s] %s (attempt %d/%d)", label, exc, attempt + 1, retries)
            await asyncio.sleep(BACKOFF_BASE * 2 ** attempt)
    return None


# --------------------------------------------------------------------------- #
# Country resolution (the old code silently turned a missing country into India)
# --------------------------------------------------------------------------- #

_COUNTRIES = {  # fallback when pycountry is not installed
    "IN": ("IND", "India"), "US": ("USA", "United States"), "GB": ("GBR", "United Kingdom"),
    "DE": ("DEU", "Germany"), "FR": ("FRA", "France"), "IT": ("ITA", "Italy"),
    "ES": ("ESP", "Spain"), "NL": ("NLD", "Netherlands"), "EU": ("EUU", "European Union"),
    "CN": ("CHN", "China"), "JP": ("JPN", "Japan"), "CA": ("CAN", "Canada"),
    "AU": ("AUS", "Australia"), "BR": ("BRA", "Brazil"), "ZA": ("ZAF", "South Africa"),
    "SG": ("SGP", "Singapore"), "AE": ("ARE", "United Arab Emirates"), "ID": ("IDN", "Indonesia"),
}
_WORLD = {"iso2": "WW", "iso3": "WLD", "name": "the world", "resolved": True}


def resolve_country(code: str | None) -> dict[str, Any]:
    """ISO-2 (or ISO-3) -> {iso2, iso3, name, resolved}. 'WW'/empty -> World Bank world
    aggregate (WLD). Unknown codes also fall back to WLD but with resolved=False."""
    raw = (code or "").strip().upper()
    if raw == "UK":
        raw = "GB"
    if raw in ("", "WW", "WLD", "WORLD"):
        return dict(_WORLD)
    rec = None
    if pycountry is not None and len(raw) in (2, 3):
        try:
            rec = (pycountry.countries.get(alpha_2=raw) if len(raw) == 2
                   else pycountry.countries.get(alpha_3=raw))
        except (KeyError, LookupError):
            rec = None
    if rec is not None:
        return {"iso2": rec.alpha_2, "iso3": rec.alpha_3,
                "name": getattr(rec, "common_name", None) or rec.name, "resolved": True}
    if raw in _COUNTRIES:
        iso3, name = _COUNTRIES[raw]
        return {"iso2": raw, "iso3": iso3, "name": name, "resolved": True}
    logger.warning("[country] could not resolve %r; using world aggregate", code)
    return {**_WORLD, "resolved": False}


# --------------------------------------------------------------------------- #
# Structured indicators: DBnomics (World Bank WDI) with World Bank API fallback
# --------------------------------------------------------------------------- #

# (indicator code, label, unit)
WB_INDICATORS: dict[str, list[tuple[str, str, str]]] = {
    "macro": [
        ("NY.GDP.MKTP.KD.ZG", "GDP growth (annual %)", "%"),
        ("FP.CPI.TOTL.ZG", "Inflation, consumer prices (annual %)", "%"),
        ("FR.INR.RINR", "Real interest rate (%)", "%"),
    ],
    "market": [
        ("SL.EMP.SELF.ZS", "Self-employed (% of total employment)", "%"),
        ("SL.TLF.TOTL.IN", "Labor force, total", "people"),
        ("IT.NET.USER.ZS", "Individuals using the Internet (% of population)", "%"),
    ],
}


def _points(periods: Iterable[Any] | None, values: Iterable[Any] | None,
            keep: int = 6) -> list[tuple[str, float]]:
    pts: list[tuple[str, float]] = []
    for p, v in zip(periods or [], values or []):
        if v is None or v == "NA":
            continue
        try:
            pts.append((str(p), float(v)))
        except (TypeError, ValueError):
            continue
    return pts[-keep:]


def _fmt(value: float, unit: str) -> str:
    return f"{value:,.0f}" if unit == "people" else f"{value:,.2f}{'%' if unit == '%' else ''}"


async def _fetch_one_indicator(client: httpx.AsyncClient, parameter: str,
                               spec: tuple[str, str, str], country: dict) -> dict | None:
    code, label, unit = spec
    iso3 = country["iso3"]
    via, url = "dbnomics", f"https://api.db.nomics.world/v22/series/WB/WDI/A-{code}-{iso3}?observations=1"
    data = await _get_json(client, url, label="DBnomics")
    docs = ((data or {}).get("series") or {}).get("docs") or []
    pts = _points(docs[0].get("period"), docs[0].get("value")) if docs else []

    if not pts:  # fallback: the World Bank API itself
        via = "worldbank_api"
        base = f"https://api.worldbank.org/v2/country/{iso3}/indicator/{code}"
        url = f"{base}?format=json&mrv=8"
        data = await _get_json(client, base, {"format": "json", "mrv": 8}, label="WorldBank")
        rows = data[1] if isinstance(data, list) and len(data) > 1 and data[1] else []
        pts = sorted(_points([r.get("date") for r in rows], [r.get("value") for r in rows]),
                     key=lambda p: p[0])[-6:]
    if not pts:
        return None

    year, value = pts[-1]
    return RawEvidenceItem(
        parameter=parameter, source_type="dbnomics" if via == "dbnomics" else "worldbank_api",
        source_url=url, title=f"World Bank WDI: {label} ({year})",
        raw_content=(f"According to the World Bank (World Development Indicators), the {label} "
                     f"for {country['name']} in {year} was {_fmt(value, unit)}."),
        metadata={
            "provider": "World Bank", "dataset": "WDI", "via": via,
            "indicator_code": code, "indicator_name": label, "unit": unit,
            "year": year, "value": value,
            "history": [{"year": y, "value": v} for y, v in pts],
            "country_iso2": country["iso2"], "country_iso3": iso3,
            "country_name": country["name"], "country_resolved": country["resolved"],
            "license": "CC BY 4.0", "attribution": "World Bank, World Development Indicators",
            "evidence_label": "sourced",
        },
    ).to_dict()


async def _fetch_indicators(parameter: str, country_code: str | None) -> list[dict]:
    country = resolve_country(country_code)
    specs = WB_INDICATORS[parameter]
    logger.info("[indicators:%s] %s -> %s (%s)", parameter, country_code, country["iso3"], country["name"])
    async with _client() as client:
        results = await asyncio.gather(
            *(_fetch_one_indicator(client, parameter, s, country) for s in specs),
            return_exceptions=True)
    out: list[dict] = []
    for spec, res in zip(specs, results):
        if isinstance(res, Exception):
            logger.error("[indicators:%s] %s failed: %s", parameter, spec[0], res)
        elif res:
            out.append(res)
        else:
            logger.warning("[indicators:%s] no data for %s (%s)", parameter, spec[0], country["iso3"])
    return out


async def fetch_macro_indicators(country_code: str | None) -> list[dict]:
    """GDP growth, inflation, real interest rate for the plan's country (parameter 'macro')."""
    return await _fetch_indicators("macro", country_code)


async def fetch_market_indicators(country_code: str | None) -> list[dict]:
    """Self-employed share, labour force, internet users: top-down inputs for TAM/SAM."""
    return await _fetch_indicators("market", country_code)


# --------------------------------------------------------------------------- #
# Hacker News: discussions (text evidence)
# --------------------------------------------------------------------------- #

HN_SEARCH = "https://hn.algolia.com/api/v1/search"


def _hn_text(hit: dict) -> str:
    title = (hit.get("story_title") or hit.get("title") or "").strip()
    body = strip_html(hit.get("comment_text") or hit.get("story_text") or "")
    if title and body:
        return f"{title}. {body}"
    return title or body


async def fetch_community_discussions(
    parameter: str, queries: list[str], max_hits_per_query: int = 20,
    max_queries: int = 8, since_years: int = 3, concurrency: int = 4,
) -> list[dict]:
    """Hacker News stories and comments for the given queries (no DB access)."""
    qs = _unique(queries)[:max_queries]
    if not qs:
        return []
    since = int((datetime.now(timezone.utc) - timedelta(days=365 * since_years)).timestamp())
    sem = asyncio.Semaphore(concurrency)

    async with _client(10.0) as client:
        async def one(q: str) -> tuple[str, list[dict]]:
            async with sem:
                data = await _get_json(client, HN_SEARCH, {
                    "query": q, "tags": "(story,comment)", "hitsPerPage": max_hits_per_query,
                    "numericFilters": f"created_at_i>{since}"}, label="HN")
            return q, (data or {}).get("hits", [])

        results = await asyncio.gather(*(one(q) for q in qs))

    out: list[dict] = []
    seen: set[str] = set()
    for q, hits in results:
        for hit in hits:
            oid = hit.get("objectID")
            text = _hn_text(hit)
            if not oid or oid in seen or len(text) < 40:
                continue
            seen.add(oid)
            tags = hit.get("_tags") or []
            out.append(RawEvidenceItem(
                parameter=parameter, source_type="hn_algolia",
                source_url=f"https://news.ycombinator.com/item?id={oid}",
                title=hit.get("story_title") or hit.get("title") or "HN Discussion",
                raw_content=text[:3000],  # truncate to save LLM tokens
                metadata={
                    "author": hit.get("author"), "points": hit.get("points"),
                    "num_comments": hit.get("num_comments"), "created_at": hit.get("created_at"),
                    "type": "comment" if "comment" in tags else "story",
                    "story_id": hit.get("story_id"), "query": q,
                },
            ).to_dict())
    logger.info("[HN] %s: %d unique items from %d queries", parameter, len(out), len(qs))
    return out


# --------------------------------------------------------------------------- #
# Hacker News: mention counts per calendar quarter (time series for "demand")
# --------------------------------------------------------------------------- #


def quarter_windows(n: int, today: datetime | None = None) -> list[tuple[str, int, int]]:
    """Last n COMPLETED calendar quarters, oldest first: (label, start_ts, end_ts)."""
    today = today or datetime.now(timezone.utc)
    end = datetime(today.year, ((today.month - 1) // 3) * 3 + 1, 1, tzinfo=timezone.utc)
    wins = []
    for _ in range(n):
        m, y = end.month - 3, end.year
        if m < 1:
            m, y = m + 12, y - 1
        start = datetime(y, m, 1, tzinfo=timezone.utc)
        wins.append((f"{y}-Q{(m - 1) // 3 + 1}", int(start.timestamp()), int(end.timestamp())))
        end = start
    return wins[::-1]


def _trend(series: list[float]) -> tuple[float | None, str]:
    first, last = series[0], series[-1]
    if first <= 0:
        return None, "insufficient_baseline"
    pct = round((last - first) / first * 100, 1)
    return pct, ("rising" if pct >= 10 else "falling" if pct <= -10 else "flat")


async def fetch_hn_mention_trend(parameter: str, queries: list[str], quarters: int = 4,
                                 max_queries: int = 4, concurrency: int = 4) -> list[dict]:
    """One evidence item per query with a quarterly mention-count series
    (hitsPerPage=0 returns only nbHits, so this is cheap)."""
    qs = _unique(queries)[:max_queries]
    if not qs:
        return []
    wins = quarter_windows(quarters)
    sem = asyncio.Semaphore(concurrency)

    async with _client(10.0) as client:
        async def count(q: str, start: int, end: int) -> int | None:
            async with sem:
                data = await _get_json(client, HN_SEARCH, {
                    "query": q, "tags": "(story,comment)", "hitsPerPage": 0,
                    "numericFilters": f"created_at_i>={start},created_at_i<{end}"}, label="HN-trend")
            return None if data is None else int(data.get("nbHits", 0))

        grids = await asyncio.gather(*(
            asyncio.gather(*(count(q, s, e) for _, s, e in wins)) for q in qs))

    out: list[dict] = []
    for q, counts in zip(qs, grids):
        if any(c is None for c in counts):
            logger.warning("[HN-trend] incomplete series for %r, skipped", q)
            continue
        pct, direction = _trend([float(c) for c in counts])
        series = [{"period": w[0], "value": c} for w, c in zip(wins, counts)]
        total = sum(counts)
        out.append(RawEvidenceItem(
            parameter=parameter, source_type="hn_trend",
            source_url=f"https://hn.algolia.com/?type=all&query={quote(q)}",
            title=f"Hacker News mentions per quarter: {q}",
            raw_content=(f'Hacker News mentions of "{q}" per quarter: '
                         + ", ".join(f"{s['period']}={s['value']}" for s in series) + "."),
            metadata={"query": q, "series": series, "change_pct": pct, "direction": direction,
                      "total_mentions": total, "low_volume": total < 20,
                      "source": "Hacker News (Algolia)", "evidence_label": "sourced"},
        ).to_dict())
    return out


# --------------------------------------------------------------------------- #
# Wikipedia pageviews (best-effort demand proxy; matched article is recorded)
# --------------------------------------------------------------------------- #

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_VIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user"


def _month_stamp(d: datetime) -> str:
    return f"{d.year}{d.month:02d}0100"


async def fetch_wikipedia_pageviews(parameter: str, topics: list[str], months: int = 12,
                                    max_topics: int = 3) -> list[dict]:
    topics = _unique(topics)[:max_topics]
    if not topics:
        return []
    now = datetime.now(timezone.utc)
    end = datetime(now.year, now.month, 1, tzinfo=timezone.utc) - timedelta(days=1)   # last full month
    start = datetime(end.year, end.month, 1, tzinfo=timezone.utc)
    for _ in range(months - 1):
        start = datetime(start.year, start.month, 1, tzinfo=timezone.utc) - timedelta(days=1)
        start = datetime(start.year, start.month, 1, tzinfo=timezone.utc)

    out: list[dict] = []
    async with _client(10.0) as client:
        for topic in topics:
            found = await _get_json(client, WIKI_API, {
                "action": "query", "list": "search", "srsearch": topic, "srlimit": 1,
                "format": "json"}, label="Wikipedia")
            hits = ((found or {}).get("query") or {}).get("search") or []
            if not hits:
                continue
            title = hits[0]["title"]
            slug = quote(title.replace(" ", "_"), safe="")
            data = await _get_json(
                client, f"{WIKI_VIEWS}/{slug}/monthly/{_month_stamp(start)}/{_month_stamp(end)}",
                label="Wikimedia")
            items = (data or {}).get("items") or []
            if len(items) < 6:
                continue
            series = [{"period": f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}", "value": int(i["views"])}
                      for i in items]
            vals = [float(s["value"]) for s in series]
            head, tail = sum(vals[:3]) / 3, sum(vals[-3:]) / 3
            pct = round((tail - head) / head * 100, 1) if head > 0 else None
            direction = ("insufficient_baseline" if pct is None else
                         "rising" if pct >= 10 else "falling" if pct <= -10 else "flat")
            words = [w for w in re.findall(r"[a-z]{4,}", topic.lower())]
            related = any(w in title.lower() for w in words)
            out.append(RawEvidenceItem(
                parameter=parameter, source_type="wikipedia_pageviews",
                source_url=f"https://en.wikipedia.org/wiki/{slug}",
                title=f"Wikipedia pageviews: {title}",
                raw_content=(f'Monthly English-Wikipedia pageviews for "{title}" (matched to topic '
                             f'"{topic}"): ' + ", ".join(f"{s['period']}={s['value']}" for s in series) + "."),
                metadata={"topic": topic, "matched_title": title, "series": series,
                          "change_pct_last3_vs_first3": pct, "direction": direction,
                          "match_confidence": "medium" if related else "low",
                          "source": "Wikimedia Pageviews API", "license": "CC0 data",
                          "evidence_label": "sourced"},
            ).to_dict())
    return out


# --------------------------------------------------------------------------- #
# App Store: competitor listings ("competition") + low-star reviews ("pain")
# --------------------------------------------------------------------------- #

ITUNES_SEARCH = "https://itunes.apple.com/search"


async def fetch_appstore_reviews(app_terms: list[str], country_code: str | None,
                                 apps_per_term: int = 1, max_rating: int = 3,
                                 max_terms: int = 4) -> list[dict]:
    terms = _unique(app_terms)[:max_terms]
    if not terms:
        return []
    iso2 = resolve_country(country_code)["iso2"]
    cc = "us" if iso2 == "WW" else iso2.lower()
    out: list[dict] = []

    async with _client(12.0) as client:
        for term in terms:
            found = await _get_json(client, ITUNES_SEARCH, {
                "term": term, "entity": "software", "limit": 5, "country": cc}, label="iTunes")
            token = term.split()[0].lower()
            apps = [a for a in (found or {}).get("results", [])
                    if token in (a.get("trackName") or "").lower()][:apps_per_term]
            for app in apps:
                view_url = app.get("trackViewUrl") or f"https://apps.apple.com/{cc}/app/id{app['trackId']}"
                out.append(RawEvidenceItem(
                    parameter="competition", source_type="appstore_listing", source_url=view_url,
                    title=f"App Store listing: {app.get('trackName')}",
                    raw_content=(f"{app.get('trackName')} by {app.get('sellerName')}: "
                                 f"{strip_html(app.get('description'))[:600]} "
                                 f"Average rating {app.get('averageUserRating')} from "
                                 f"{app.get('userRatingCount')} ratings. Price: "
                                 f"{app.get('formattedPrice') or app.get('price')}."),
                    metadata={"matched_term": term, "app_name": app.get("trackName"),
                              "seller": app.get("sellerName"), "average_rating": app.get("averageUserRating"),
                              "rating_count": app.get("userRatingCount"), "price": app.get("price"),
                              "formatted_price": app.get("formattedPrice"), "genre": app.get("primaryGenreName"),
                              "last_updated": app.get("currentVersionReleaseDate"), "store_country": cc,
                              "evidence_label": "sourced"},
                ).to_dict())

                feed = await _get_json(
                    client,
                    f"https://itunes.apple.com/{cc}/rss/customerreviews/page=1/id={app['trackId']}/sortby=mostrecent/json",
                    label="iTunes-reviews")
                entries = (((feed or {}).get("feed") or {}).get("entry")) or []
                if isinstance(entries, dict):
                    entries = [entries]
                for e in entries:
                    if "im:rating" not in e:   # first entry can be app metadata
                        continue
                    try:
                        rating = int(e["im:rating"]["label"])
                        title = e["title"]["label"]
                        body = e["content"]["label"]
                        rid = e["id"]["label"]
                    except (KeyError, ValueError, TypeError):
                        continue
                    if rating > max_rating:
                        continue
                    author = ((e.get("author") or {}).get("name") or {}).get("label") or ""
                    out.append(RawEvidenceItem(
                        parameter="pain", source_type="appstore_review",
                        source_url=f"{view_url}#review-{rid}",   # unique per review (dedupe key)
                        title=f"{app.get('trackName')} review ({rating} star)",
                        raw_content=f"{title}. {body}"[:3000],
                        metadata={"app_name": app.get("trackName"), "rating": rating,
                                  "version": (e.get("im:version") or {}).get("label"),
                                  "created_at": (e.get("updated") or {}).get("label"),
                                  "author_hash": hashlib.sha1(author.encode()).hexdigest()[:12] if author else None,
                                  "matched_term": term, "store_country": cc},
                    ).to_dict())
    return out


# --------------------------------------------------------------------------- #
# Vertex AI Search: unstructured pages (market reports, competitor pricing, regulation)
# --------------------------------------------------------------------------- #
#
# Contract with validate_search._vertex:  fetch_vertex_search(legacy_name, queries) -> list[dict].
# normalise() drops every item without source_url or raw_content, so each hit must arrive with
# TEXT.  A hit that carries only a title and a URL is not evidence.
#
# The text comes from Vertex itself: snippets, extractive segments/answers, or the page's meta
# description.  Per Google's docs, on WEBSITE data stores snippets need Enterprise edition
# features, and extractive answers/segments also need advanced website indexing.  If the engine
# returns hits but none with text, the collector raises with that explanation so
# collection_report shows "error", not a misleading "empty".
#
# The Google SDK and src.core.settings are imported lazily so the other collectors in this
# module stay importable (and testable) without GCP dependencies.

VERTEX_QUERY_TIMEOUT_S = 25.0    # per query; the orchestrator's 90 s job budget covers two waves
VERTEX_MAX_ATTEMPTS = 3          # attempts per query; only transient API errors are retried
VERTEX_MAX_QUERIES = 8           # same cap as validate_search.MAX_QUERIES
VERTEX_MAX_ITEMS = 30            # evidence items per call (one call = one parameter)
VERTEX_MAX_CONTENT_CHARS = 3000  # same truncation as the Hacker News collector
VERTEX_MIN_CONTENT_CHARS = 40    # same floor as the Hacker News collector

_TRACKING_KEYS = {"gclid", "fbclid", "mc_cid", "mc_eid"}
_NEGATIVE_TERM = re.compile(r"(?<!\S)-\S+")   # "-quora", "-site:reddit.com"
_OR_WORD = re.compile(r"\bOR\b")


def _vertex_settings() -> Any:
    from src.core.settings import settings   # lazy: see the note above
    return settings


def _build_vertex_client() -> Any:
    from google.cloud import discoveryengine_v1 as discoveryengine
    from google.oauth2 import service_account

    creds_info = json.loads(_vertex_settings().GOOGLE_APPLICATION_CREDENTIALS_JSON)
    credentials = service_account.Credentials.from_service_account_info(
        creds_info, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return discoveryengine.SearchServiceAsyncClient(credentials=credentials)


def _vertex_serving_config() -> str:
    s = _vertex_settings()
    return (f"projects/{s.DISCOVERY_PROJECT_ID}/locations/{s.DISCOVERY_LOCATION}"
            f"/collections/{s.DISCOVERY_COLLECTION}/engines/{s.DISCOVERY_ENGINE_ID_VALIDATE}"
            f"/servingConfigs/{s.DISCOVERY_SERVING_CONFIG}")


def _vertex_request(serving_cfg: str, query: str, page_size: int, extractive: bool) -> Any:
    """Search request that asks for text: snippets always, extractive content when allowed."""
    from google.cloud import discoveryengine_v1 as discoveryengine

    spec = discoveryengine.SearchRequest.ContentSearchSpec
    parts: dict[str, Any] = {"snippet_spec": spec.SnippetSpec(return_snippet=True)}
    if extractive:
        parts["extractive_content_spec"] = spec.ExtractiveContentSpec(
            max_extractive_answer_count=1, max_extractive_segment_count=2)
    return discoveryengine.SearchRequest(
        serving_config=serving_cfg, query=query, page_size=page_size,
        content_search_spec=spec(**parts))


async def _close_vertex_client(client: Any) -> None:
    try:
        await client.transport.close()
    except Exception:  # noqa: BLE001 - cleanup must never mask the result
        logger.debug("[vertex] client close failed", exc_info=True)


def _clean_vertex_query(query: str | None) -> str:
    """The plan's institutional queries may carry Google operators ("-quora -reddit", "OR").
    The engine indexes only the curated sites, so the exclusions have nothing to exclude, and
    it is unverified that Vertex honours operators at all (it may search for them as words)."""
    q = _OR_WORD.sub(" ", _NEGATIVE_TERM.sub(" ", query or ""))
    return re.sub(r"\s+", " ", q).strip()


def _canonical_url(url: str | None) -> str:
    """Stored URL and dedupe key: no fragment, tracking params or trailing slash, lower-case
    host.  '' for anything that is not an http(s) URL."""
    try:
        p = urlsplit((url or "").strip())
    except ValueError:
        return ""
    if p.scheme not in ("http", "https") or not p.netloc:
        return ""
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not (k.lower().startswith("utm_") or k.lower() in _TRACKING_KEYS)]
    return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/") or "/", urlencode(query), ""))


def _plain(value: Any) -> Any:
    """proto-plus Struct values (MapComposite / RepeatedComposite) -> plain dict / list."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_plain(v) for v in value]
    return value


def _vertex_texts(entries: Any, field: str) -> list[str]:
    out: list[str] = []
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        status = e.get("snippet_status")
        if status and status != "SUCCESS":    # NO_SNIPPET_AVAILABLE carries placeholder text
            continue
        text = strip_html(e.get(field))
        if text:
            out.append(text)
    return out


def _vertex_content(derived: dict) -> tuple[str, str]:
    """(text, kind).  Extractive segments and answers are richest, then snippets, then the
    page's own meta description.  kind is 'extractive', 'snippet', 'description' or ''."""
    parts: list[tuple[str, str]] = []
    for key in ("extractive_segments", "extractive_answers"):
        parts += [(t, "extractive") for t in _vertex_texts(derived.get(key), "content")]
    parts += [(t, "snippet") for t in _vertex_texts(derived.get("snippets"), "snippet")]
    if not parts:
        pagemap = derived.get("pagemap")
        tags = pagemap.get("metatags") if isinstance(pagemap, dict) else None
        first = tags[0] if isinstance(tags, list) and tags and isinstance(tags[0], dict) else {}
        desc = strip_html(first.get("og:description") or first.get("description"))
        if desc:
            parts.append((desc, "description"))

    kept: list[str] = []
    for text, _ in parts:
        if not any(text.lower() in k.lower() for k in kept):   # drop repeats and fragments
            kept.append(text)
    kind = next((k for _, k in parts), "")
    return "\n\n".join(kept)[:VERTEX_MAX_CONTENT_CHARS], kind


def _vertex_hits(response: Any, query: str) -> tuple[list[dict], int]:
    """(hits that have a URL and text, number of results Vertex returned)."""
    results = list(getattr(response, "results", None) or [])
    hits: list[dict] = []
    for rank, result in enumerate(results, start=1):
        doc = getattr(result, "document", None)
        derived, struct = (_plain(getattr(doc, "derived_struct_data", None)),
                           _plain(getattr(doc, "struct_data", None)))
        derived = derived if isinstance(derived, dict) else {}
        struct = struct if isinstance(struct, dict) else {}
        url = _canonical_url(derived.get("link") or struct.get("link"))
        if not url:
            continue
        text, kind = _vertex_content(derived)
        if len(text) < VERTEX_MIN_CONTENT_CHARS:
            continue
        hits.append({"url": url, "title": strip_html(derived.get("title") or struct.get("title")),
                     "text": text, "kind": kind, "rank": rank, "query": query})
    return hits, len(results)


def _vertex_transient(exc: Exception) -> bool:
    from google.api_core import exceptions as gexc
    return isinstance(exc, (gexc.ResourceExhausted, gexc.TooManyRequests, gexc.ServiceUnavailable,
                            gexc.DeadlineExceeded, gexc.InternalServerError, gexc.GatewayTimeout,
                            gexc.Aborted))


async def _vertex_search_one(client: Any, serving_cfg: str, query: str, page_size: int,
                             state: dict) -> tuple[list[dict], int, str | None]:
    """(hits, results returned, error).  Never raises for API errors or timeouts, so one bad
    query cannot discard the others; the caller decides what a total failure means."""
    from google.api_core import exceptions as gexc

    for attempt in range(1, VERTEX_MAX_ATTEMPTS + 1):
        extractive = state["extractive"]
        try:
            request = _vertex_request(serving_cfg, query, page_size, extractive)
            response = await asyncio.wait_for(client.search(request), timeout=VERTEX_QUERY_TIMEOUT_S)
            hits, returned = _vertex_hits(response, query)
            return hits, returned, None
        except asyncio.TimeoutError:
            return [], 0, f"timeout after {VERTEX_QUERY_TIMEOUT_S:g}s"
        except gexc.InvalidArgument as exc:
            if extractive and attempt < VERTEX_MAX_ATTEMPTS:
                if state["extractive"]:
                    logger.warning("[vertex] request rejected (%s); falling back to snippets only",
                                   str(exc)[:200])
                state["extractive"] = False   # engine has no extractive content: snippets only
                continue
            return [], 0, f"InvalidArgument: {str(exc)[:300]}"
        except gexc.GoogleAPICallError as exc:
            if _vertex_transient(exc) and attempt < VERTEX_MAX_ATTEMPTS:
                delay = BACKOFF_BASE * 2 ** (attempt - 1)
                logger.warning("[vertex] transient error for %r (%s); retry in %.0fs",
                               query, str(exc)[:200], delay)
                await asyncio.sleep(delay)
                continue
            return [], 0, f"{type(exc).__name__}: {str(exc)[:300]}"
        except Exception as exc:  # noqa: BLE001
            return [], 0, f"{type(exc).__name__}: {str(exc)[:300]}"
    return [], 0, "retries exhausted"


async def fetch_vertex_search(parameter: str, queries: list[str],
                              max_items: int = VERTEX_MAX_ITEMS,
                              max_queries: int = VERTEX_MAX_QUERIES,
                              concurrency: int = 4) -> list[dict]:
    """Search the curated Vertex AI Search engine (reports, pricing pages, regulation) for one
    parameter.  `parameter` is stored on every item exactly as given: validate_search passes the
    legacy name (e.g. "pain_point_severity") and maps it back to the canonical key.

    - Queries run `concurrency` at a time, each with its own timeout and retry on 429/5xx.
    - A failing query is skipped.  If EVERY query fails this raises, and it also raises when
      Vertex returns results but none carry text, so collection_report says "error", not "empty".
    - Results are interleaved across queries (rank 1 of each query first), de-duplicated by
      canonical URL (matching queries are kept in metadata) and capped at `max_items`.
    """
    qs = _unique(_clean_vertex_query(q) for q in queries or [])[:max_queries]
    if not qs:
        return []

    serving_cfg = _vertex_serving_config()
    page_size = int(_vertex_settings().DISCOVERY_PAGE_SIZE)
    client = _build_vertex_client()
    state = {"extractive": True}
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(q: str) -> tuple[list[dict], int, str | None]:
        async with sem:
            return await _vertex_search_one(client, serving_cfg, q, page_size, state)

    try:
        outcomes = await asyncio.gather(*(one(q) for q in qs))
    finally:
        await _close_vertex_client(client)

    errors = [err for _, _, err in outcomes if err]
    returned = sum(n for _, n, _ in outcomes)
    if errors:
        logger.warning("[vertex:%s] %d/%d queries failed; first error: %s",
                       parameter, len(errors), len(qs), errors[0])
    if len(errors) == len(qs):
        raise RuntimeError(f"Vertex search failed for all {len(qs)} queries: {errors[0]}")

    merged: dict[str, dict] = {}
    for i in range(max((len(h) for h, _, _ in outcomes), default=0)):
        for hits, _, _ in outcomes:
            if i >= len(hits):
                continue
            hit = hits[i]
            if hit["url"] in merged:
                merged[hit["url"]]["queries"].append(hit["query"])
            elif len(merged) < max_items:
                merged[hit["url"]] = {**hit, "queries": [hit["query"]]}

    if not merged and returned:
        raise RuntimeError(
            f"Vertex returned {returned} results for {parameter} but none carried usable text "
            "(no snippets or extractive content). On website data stores these need Enterprise "
            "edition features; extractive content also needs advanced website indexing.")

    out: list[dict] = []
    for hit in merged.values():
        host = (urlsplit(hit["url"]).hostname or "").removeprefix("www.")
        out.append(RawEvidenceItem(
            parameter=parameter, source_type="vertex_search", source_url=hit["url"],
            title=hit["title"] or host, raw_content=hit["text"],
            metadata={"query": hit["queries"][0], "matched_queries": hit["queries"],
                      "rank": hit["rank"], "domain": host, "content_kind": hit["kind"],
                      "source": "Vertex AI Search"},
        ).to_dict())
    logger.info("[vertex:%s] %d queries -> %d results -> %d evidence items",
                parameter, len(qs), returned, len(out))
    return out