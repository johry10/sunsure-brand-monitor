#!/usr/bin/env python3
"""GDELT and Bing News RSS supplementary article sources.
No API key required for either.

GDELT (Global Database of Events, Language, and Tone):
  - Free public REST API, updated every 15 min since 2013
  - Returns up to 250 results per query with date range filtering
  - Surfaces ANI/wire-service pickups, international outlets, and
    outlets Google News RSS under-ranks (Business Today, The Tribune, etc.)
  - Rate limit: ~1 req/sec; we use 2s sleep to stay safe

Bing News RSS:
  - Free public RSS feed, different ranking algorithm from Google
  - Real article URLs are embedded in the Bing redirect link (&url= param)
  - Source outlet name is in the news_source feed field
  - No date filter in URL — we filter locally by published_parsed
  - Returns up to 15 results per query; best for recent articles

Both are called from collect_data.py after Google News + industry RSS collection.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from time import mktime

import feedparser

# Mirrors COMPANIES in collect_data.py
COMPANY_QUERIES: dict[str, list[str]] = {
    "Sunsure":         ["Sunsure Energy", "Sunsure Solar", "Sunsure"],
    "ReNew":           ["ReNew Power", "ReNew Energy Global"],
    "Cleanmax":        ["CleanMax Solar", "Clean Max Enviro"],
    "Ampin":           ["Ampin Energy", "AMPIN Solar"],
    "Gentari/Amplus":  ["Gentari", "Amplus Solar", "Amplus Energy"],
    "Hexa Climate":    ["Hexa Climate"],
}

# Mirrors MATCH_PATTERNS in clean_data.py — used to assign articles to companies
COMPANY_PATTERNS: dict[str, list] = {
    "Sunsure":        ["sunsure"],
    "ReNew":          [re.compile(r"\brenew\b", re.I)],
    "Cleanmax":       ["cleanmax", "clean max"],
    "Ampin":          ["ampin"],
    "Gentari/Amplus": ["gentari", "amplus"],
    "Hexa Climate":   ["hexa climate"],
}

_GDELT_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_BING_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# ── helpers ──────────────────────────────────────────────────────────────────

def _matches_company(title: str, snippet: str, company: str) -> bool:
    haystack = title + " " + snippet
    for p in COMPANY_PATTERNS.get(company, []):
        if isinstance(p, re.Pattern):
            if p.search(haystack):
                return True
        elif p.lower() in haystack.lower():
            return True
    return False


def _extract_bing_real_url(redirect_url: str) -> str:
    """Pull the real article URL out of Bing's apiclick redirect."""
    try:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(redirect_url).query)
        urls = params.get("url", [])
        return urls[0] if urls else ""
    except Exception:
        return ""


def _gdelt_date(seendate: str) -> str | None:
    """Parse GDELT seendate '20260522T123456Z' → ISO datetime string."""
    try:
        return datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").isoformat()
    except Exception:
        return None


# ── GDELT ─────────────────────────────────────────────────────────────────────

def _fetch_gdelt_query(query: str, month_start: date, month_end: date) -> list[dict]:
    """Single GDELT query. Returns raw article list."""
    start_str = month_start.strftime("%Y%m%d") + "000000"
    end_str = (month_end + timedelta(days=1)).strftime("%Y%m%d") + "000000"
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc"
        f"?query={urllib.parse.quote(query)}"
        "&mode=artlist&format=json&maxrecords=250"
        f"&startdatetime={start_str}&enddatetime={end_str}"
        "&sort=datedesc"
    )
    req = urllib.request.Request(url, headers={"User-Agent": _GDELT_UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        return data.get("articles") or []
    except Exception as e:
        print(f"    [GDELT] error: {e}")
        return []


def fetch_gdelt_articles(month_start: date, month_end: date) -> dict[str, list[dict]]:
    """Fetch GDELT for all companies in the given month window.
    Uses one Boolean query per company (term1 OR term2 OR ...) to stay
    under GDELT's ~1 req/sec rate limit. Returns {company: [article, ...]}."""
    result: dict[str, list[dict]] = {c: [] for c in COMPANY_QUERIES}
    seen_urls: set[str] = set()

    for company, queries in COMPANY_QUERIES.items():
        # Combine all search terms into one GDELT Boolean query
        boolean_query = " OR ".join(f'"{q}"' for q in queries)
        raw = _fetch_gdelt_query(boolean_query, month_start, month_end)

        for a in raw:
            art_url = a.get("url", "")
            if not art_url or art_url in seen_urls:
                continue
            seen_urls.add(art_url)

            title = (a.get("title") or "").strip()
            pub = _gdelt_date(a.get("seendate", ""))
            domain = a.get("domain", "")

            art = {
                "title": title,
                "url": art_url,
                "source": domain,
                "published": pub,
                "snippet": "",
                "_feed_source": "gdelt",
            }

            # Assign to matching companies
            for c in COMPANY_PATTERNS:
                if _matches_company(title, "", c):
                    result[c].append(art)

        time.sleep(3)  # GDELT rate limit: ~1 req/sec; 3s gives comfortable margin

    return result


# ── Bing News RSS ─────────────────────────────────────────────────────────────

def _fetch_bing_query(query: str) -> list:
    """Single Bing News RSS query. Returns feedparser entries."""
    url = f"https://www.bing.com/news/search?q={urllib.parse.quote(query)}&format=rss"
    try:
        d = feedparser.parse(url, agent=_BING_UA)
        return d.entries
    except Exception:
        return []


def fetch_bing_articles(month_start: date, month_end: date) -> dict[str, list[dict]]:
    """Fetch Bing News RSS for all companies, filter by date window.
    Returns {company: [article, ...]}."""
    result: dict[str, list[dict]] = {c: [] for c in COMPANY_QUERIES}
    seen_urls: set[str] = set()

    for company, queries in COMPANY_QUERIES.items():
        for query in queries:
            entries = _fetch_bing_query(f'"{query}"')
            for e in entries:
                # Parse date and filter to month window
                if not e.get("published_parsed"):
                    continue
                try:
                    pub_date = datetime.fromtimestamp(mktime(e.published_parsed)).date()
                except Exception:
                    continue
                if not (month_start <= pub_date <= month_end):
                    continue

                # Extract real URL from Bing redirect
                real_url = _extract_bing_real_url(e.get("link", ""))
                if not real_url or real_url in seen_urls:
                    continue
                seen_urls.add(real_url)

                title = (e.get("title") or "").strip()
                snippet = (e.get("summary") or "")[:300]
                source = e.get("news_source", "") or ""
                pub_iso = datetime.combine(pub_date, datetime.min.time()).isoformat()

                art = {
                    "title": title,
                    "url": real_url,
                    "source": source,
                    "published": pub_iso,
                    "snippet": snippet,
                    "_feed_source": "bing_rss",
                }

                for c in COMPANY_PATTERNS:
                    if _matches_company(title, snippet, c):
                        result[c].append(art)

            time.sleep(0.5)

    return result


# ── combined entry point ──────────────────────────────────────────────────────

def fetch_supplementary_articles(
    month_start: date,
    month_end: date,
    use_gdelt: bool = True,
    use_bing: bool = True,
) -> dict[str, list[dict]]:
    """Fetch from GDELT and/or Bing News RSS for all companies.
    Returns {company: [article, ...]} with articles deduplicated across sources."""
    result: dict[str, list[dict]] = {c: [] for c in COMPANY_QUERIES}
    seen_urls: set[str] = set()

    def _merge(source_result: dict[str, list[dict]]) -> None:
        for company, arts in source_result.items():
            for art in arts:
                if art.get("url") and art["url"] not in seen_urls:
                    seen_urls.add(art["url"])
                    result[company].append(art)

    if use_gdelt:
        _merge(fetch_gdelt_articles(month_start, month_end))

    if use_bing:
        _merge(fetch_bing_articles(month_start, month_end))

    return result


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from calendar import monthrange
    today = date.today()
    start = today.replace(day=1)
    end = today.replace(day=monthrange(today.year, today.month)[1])
    print(f"Testing supplementary feeds for {start} → {end}\n")

    results = fetch_supplementary_articles(start, end)
    total = sum(len(v) for v in results.values())
    print(f"Total articles: {total}")
    for company, arts in results.items():
        if arts:
            print(f"\n{company}: {len(arts)} article(s)")
            for a in arts[:5]:
                src = a.get("source", "")[:25]
                feed = a.get("_feed_source", "")
                print(f"  [{feed}] [{src:<25}] {a['title'][:70]}")
