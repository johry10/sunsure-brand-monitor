#!/usr/bin/env python3
"""Collect 12 months of SOV data (Apr 2024 – Mar 2025) for Sunsure + competitors.
Uses date-windowed Google News RSS + direct industry RSS feeds. Outputs sov_data_fy25.json."""
from __future__ import annotations

import json
import time
import urllib.parse
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from time import mktime

import feedparser
from industry_feeds import fetch_industry_articles

ROOT = Path(__file__).parent

COMPANIES: dict[str, list[str]] = {
    "Sunsure":         ["Sunsure Energy", "Sunsure Solar"],
    "ReNew":           ["ReNew Power", "ReNew Energy Global"],
    "Cleanmax":        ["CleanMax Solar", "Clean Max Enviro"],
    "Ampin":           ["Ampin Energy", "AMPIN Solar"],
    "Gentari/Amplus":  ["Gentari", "Amplus Solar", "Amplus Energy"],
    "Hexa Climate":    ["Hexa Climate"],
}

# FY 2024-25: Apr 2024 to Mar 2025
MONTHS: list[dict] = []
for y, m in [(2024, mm) for mm in range(4, 13)] + [(2025, mm) for mm in range(1, 4)]:
    last = monthrange(y, m)[1]
    MONTHS.append({
        "label": f"{y}-{m:02d}",
        "display": date(y, m, 1).strftime("%b %Y"),
        "start": date(y, m, 1),
        "end": date(y, m, last),
    })


def google_news_url(query: str, after: date, before: date) -> str:
    # Google News 'before:' is exclusive, so add 1 day to include articles on 'before' date
    before_incl = before + timedelta(days=1)
    q = f'"{query}" after:{after.isoformat()} before:{before_incl.isoformat()}'
    return (
        f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}"
        f"&hl=en-IN&gl=IN&ceid=IN:en"
    )


def parse_pub(entry) -> str | None:
    if entry.get("published_parsed"):
        try:
            return datetime.fromtimestamp(mktime(entry.published_parsed)).isoformat()
        except Exception:
            return None
    return None


def fetch_month(query: str, start: date, end: date) -> list[dict]:
    d = feedparser.parse(google_news_url(query, start, end))
    out = []
    for e in d.entries:
        link = e.get("link", "")
        if not link:
            continue
        out.append({
            "title": e.get("title", "").strip(),
            "url": link,
            "source": (e.get("source", {}) or {}).get("title") or "",
            "published": parse_pub(e),
            "snippet": (e.get("summary", "") or "")[:300],
        })
    return out


def find_highlight(articles: list[dict]) -> dict | None:
    if not articles:
        return None
    clusters: dict[str, list[dict]] = defaultdict(list)
    for a in articles:
        key = " ".join(a["title"].lower().split()[:6])
        clusters[key].append(a)
    biggest = max(clusters.values(), key=len)
    return max(biggest, key=lambda a: len(a["title"]))


def main():
    print(f"Collecting FY25 SOV data (Apr 2024 – Mar 2025)")
    print(f"{len(COMPANIES)} companies × {len(MONTHS)} months")
    print(f"= {sum(len(q) for q in COMPANIES.values()) * len(MONTHS)} queries total\n")

    data: dict[str, dict[str, list[dict]]] = {c: {} for c in COMPANIES}
    start_time = time.time()

    for company, queries in COMPANIES.items():
        print(f"\n{company}:")
        for month in MONTHS:
            seen = set()
            articles = []
            for q in queries:
                for art in fetch_month(q, month["start"], month["end"]):
                    if art["url"] in seen:
                        continue
                    seen.add(art["url"])
                    articles.append(art)
            data[company][month["label"]] = articles
            print(f"  {month['label']}: {len(articles):>3} articles (Google News)")
            time.sleep(0.25)

    # Supplement with direct industry RSS feeds
    # Note: industry feeds only return recent articles (~last 30 days), so
    # for FY25 historical data the incremental gain will be minimal.
    print("\nFetching industry RSS feeds...")
    feed_added = 0
    for month in MONTHS:
        industry = fetch_industry_articles(month["start"], month["end"])
        for company, arts in industry.items():
            if company not in data:
                continue
            existing_urls = {a["url"] for a in data[company][month["label"]]}
            new_arts = [a for a in arts if a["url"] not in existing_urls]
            data[company][month["label"]].extend(new_arts)
            feed_added += len(new_arts)
    print(f"  Added {feed_added} articles not already in Google News")

    highlights = {
        c: {m["label"]: find_highlight(data[c][m["label"]]) for m in MONTHS}
        for c in COMPANIES
    }

    out = {
        "generated_at": datetime.now().isoformat(),
        "fy": "FY25",
        "months": [{"label": m["label"], "display": m["display"]} for m in MONTHS],
        "companies": list(COMPANIES.keys()),
        "data": data,
        "highlights": highlights,
    }

    out_path = ROOT / "sov_data_fy25.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))

    elapsed = time.time() - start_time
    total_articles = sum(len(arts) for c in COMPANIES for arts in data[c].values())
    print(f"\n✅ Saved {out_path.name}")
    print(f"   Total articles: {total_articles}  |  Time: {elapsed:.0f}s  |  File: {out_path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
