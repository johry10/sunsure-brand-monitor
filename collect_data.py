#!/usr/bin/env python3
"""Collect rolling 13-month SOV data for Sunsure + competitors.
Always covers the last 12 complete months + the current partial month.
Uses Google News RSS + direct industry RSS feeds. Outputs sov_data.json."""
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


def _build_months(n_back: int = 12) -> list[dict]:
    """Return list of month dicts from n_back months ago through current month."""
    today = date.today()
    months = []
    for i in range(n_back, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        last = monthrange(y, m)[1]
        # For the current month use today as end date (partial month)
        end = today if i == 0 else date(y, m, last)
        months.append({
            "label": f"{y}-{m:02d}",
            "display": date(y, m, 1).strftime("%b %Y"),
            "start": date(y, m, 1),
            "end": end,
        })
    return months


MONTHS = _build_months(n_back=12)


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
    """Pick the article representing the dominant story for the month.
    Cluster by first 6 words of title; biggest cluster wins; longest title in cluster."""
    if not articles:
        return None
    clusters: dict[str, list[dict]] = defaultdict(list)
    for a in articles:
        key = " ".join(a["title"].lower().split()[:6])
        clusters[key].append(a)
    biggest = max(clusters.values(), key=len)
    return max(biggest, key=lambda a: len(a["title"]))


def main():
    print(f"Collecting SOV data for {len(COMPANIES)} companies × {len(MONTHS)} months")
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
            time.sleep(0.25)  # be nice to Google

    # Supplement with direct industry RSS feeds (Mercom, pv magazine India,
    # Solar Quarter, Renewable Watch, Wind Insider, PV Tech)
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

    # Build highlights
    highlights = {
        c: {m["label"]: find_highlight(data[c][m["label"]]) for m in MONTHS}
        for c in COMPANIES
    }

    out = {
        "generated_at": datetime.now().isoformat(),
        "months": [{"label": m["label"], "display": m["display"]} for m in MONTHS],
        "companies": list(COMPANIES.keys()),
        "data": data,
        "highlights": highlights,
    }

    out_path = ROOT / "sov_data.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))

    elapsed = time.time() - start_time
    total_articles = sum(len(arts) for c in COMPANIES for arts in data[c].values())
    print(f"\n✅ Saved {out_path.name}")
    print(f"   Total articles: {total_articles}  |  Time: {elapsed:.0f}s  |  File: {out_path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
