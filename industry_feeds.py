#!/usr/bin/env python3
"""Fetch articles from free Indian renewable-energy RSS feeds.
Used as a supplement to Google News RSS in collect_data.py.

These feeds don't support date filtering — we fetch all entries and
filter locally by date range + company name match."""
from __future__ import annotations

import re
import time
from datetime import date, datetime
from time import mktime

import feedparser

# Verified live feeds as of May 2026
FEED_URLS: list[str] = [
    "https://mercomindia.com/feed/",
    "https://www.pv-magazine-india.com/feed/",
    "https://solarquarter.com/feed/",
    "https://renewablewatch.in/feed/",
    "https://windinsider.com/feed/",
    "https://www.pv-tech.org/feed/",
]

# Company name patterns — must appear in title or snippet.
# Mirrors clean_data.py MATCH_PATTERNS.
COMPANY_PATTERNS: dict[str, list] = {
    "Sunsure":        ["sunsure"],
    "ReNew":          [re.compile(r"\brenew\b", re.I)],
    "Cleanmax":       ["cleanmax", "clean max"],
    "Ampin":          ["ampin"],
    "Gentari/Amplus": ["gentari", "amplus"],
    "Hexa Climate":   ["hexa climate"],
}


def _parse_date(entry) -> date | None:
    if entry.get("published_parsed"):
        try:
            return datetime.fromtimestamp(mktime(entry.published_parsed)).date()
        except Exception:
            return None
    return None


def _matches_company(title: str, snippet: str, company: str) -> bool:
    haystack = title + " " + snippet
    for p in COMPANY_PATTERNS.get(company, []):
        if isinstance(p, re.Pattern):
            if p.search(haystack):
                return True
        elif p.lower() in haystack.lower():
            return True
    return False


def fetch_industry_articles(
    month_start: date,
    month_end: date,
) -> dict[str, list[dict]]:
    """Return {company: [article, ...]} for all articles from industry feeds
    that fall within [month_start, month_end] and mention a tracked company."""

    result: dict[str, list[dict]] = {c: [] for c in COMPANY_PATTERNS}
    seen_urls: set[str] = set()

    for url in FEED_URLS:
        try:
            feed = feedparser.parse(url)
        except Exception:
            continue

        for entry in feed.entries:
            pub = _parse_date(entry)
            if pub is None or not (month_start <= pub <= month_end):
                continue

            link = entry.get("link", "")
            if not link or link in seen_urls:
                continue
            seen_urls.add(link)

            title = (entry.get("title") or "").strip()
            snippet = (entry.get("summary") or "")[:300]
            source = (entry.get("source", {}) or {}).get("title") or _source_from_url(url)
            pub_iso = datetime.combine(pub, datetime.min.time()).isoformat()

            art = {
                "title": title,
                "url": link,
                "source": source,
                "published": pub_iso,
                "snippet": snippet,
                "_feed_source": "industry_rss",
            }

            for company in COMPANY_PATTERNS:
                if _matches_company(title, snippet, company):
                    result[company].append(art)

        time.sleep(0.1)

    return result


def _source_from_url(feed_url: str) -> str:
    mapping = {
        "mercomindia.com":       "Mercomindia.com",
        "pv-magazine-india.com": "pv magazine India",
        "solarquarter.com":      "SolarQuarter",
        "renewablewatch.in":     "Renewable Watch Magazine",
        "windinsider.com":       "Wind Insider",
        "pv-tech.org":           "PV Tech",
    }
    for domain, name in mapping.items():
        if domain in feed_url:
            return name
    return feed_url


if __name__ == "__main__":
    # Quick test — fetch articles for current month
    today = date.today()
    start = today.replace(day=1)
    from calendar import monthrange
    end = today.replace(day=monthrange(today.year, today.month)[1])
    print(f"Fetching industry feeds for {start} → {end}\n")
    results = fetch_industry_articles(start, end)
    for company, arts in results.items():
        if arts:
            print(f"{company}: {len(arts)} article(s)")
            for a in arts:
                print(f"  [{a['source'][:25]}] {a['title'][:80]}")
