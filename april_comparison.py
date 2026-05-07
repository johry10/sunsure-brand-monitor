#!/usr/bin/env python3
"""One-off: April 2026 news coverage comparison for Sunsure vs competitors.
No LLM/API needed — pure RSS scrape + date filter + counts."""
from __future__ import annotations

import urllib.parse
from collections import Counter
from datetime import datetime
from time import mktime

import feedparser

COMPANIES = {
    "Sunsure Energy": ["Sunsure Energy", "Sunsure Solar"],
    "ReNew": ["ReNew Power", '"ReNew" renewable'],
    "Ampin Energy": ["Ampin Energy", "AMPIN Energy"],
    "Cleanmax": ["Cleanmax Solar", "Cleanmax Enviro"],
    "Gentari": ["Gentari", "Gentari India"],
}

TARGET_YEAR = 2026
TARGET_MONTH = 4


def google_news_url(query: str) -> str:
    q = urllib.parse.quote(f'"{query}"' if " " in query and not query.startswith('"') else query)
    return (
        f"https://news.google.com/rss/search?q={q}"
        f"&hl=en-IN&gl=IN&ceid=IN:en"
    )


def fetch_for(queries: list[str]) -> list[dict]:
    seen = set()
    out = []
    for q in queries:
        url = google_news_url(q)
        d = feedparser.parse(url)
        for e in d.entries:
            link = e.get("link", "")
            if not link or link in seen:
                continue
            seen.add(link)
            pub = None
            if e.get("published_parsed"):
                try:
                    pub = datetime.fromtimestamp(mktime(e.published_parsed))
                except Exception:
                    pub = None
            out.append({
                "title": e.get("title", "").strip(),
                "url": link,
                "source": (e.get("source", {}) or {}).get("title") or "",
                "published": pub,
            })
    return out


def is_april(a: dict) -> bool:
    return bool(a["published"]) and a["published"].year == TARGET_YEAR and a["published"].month == TARGET_MONTH


def categorize(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["ppa", "power purchase", "signs", "deal", "supply", "agreement"]):
        return "Deal/PPA"
    if any(k in t for k in ["funding", "debt", "raise", "loan", "crore", "million", "billion", "investment"]):
        return "Financial"
    if any(k in t for k in ["commission", "operational", "online", "starts"]):
        return "Project go-live"
    if any(k in t for k in ["acquire", "acquisition", "merger", "buy"]):
        return "M&A"
    if any(k in t for k in ["ceo", "appoint", "hires", "joins", "exits"]):
        return "Leadership"
    if any(k in t for k in ["tender", "bid", "auction", "secured", "wins"]):
        return "Tender/Bid"
    return "Other"


print("=" * 78)
print(f"APRIL {TARGET_YEAR} — NEWS COVERAGE COMPARISON")
print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Source: Google News RSS")
print("=" * 78)

results: dict[str, dict] = {}
for name, queries in COMPANIES.items():
    print(f"\n[fetching] {name}...", end=" ", flush=True)
    arts = fetch_for(queries)
    april = [a for a in arts if is_april(a)]
    results[name] = {
        "total": len(arts),
        "april": april,
        "april_count": len(april),
        "sources": Counter(a["source"] for a in april if a["source"]).most_common(5),
        "categories": Counter(categorize(a["title"]) for a in april),
    }
    print(f"{len(arts)} total, {len(april)} in April")

print()
print("-" * 78)
print("HEADLINE SCOREBOARD")
print("-" * 78)
print(f"{'Company':<18} {'April mentions':>15} {'Most active source':>30}")
print("-" * 78)
for name, r in results.items():
    top_src = r["sources"][0][0] if r["sources"] else "—"
    print(f"{name:<18} {r['april_count']:>15} {top_src[:28]:>30}")

print()
print("-" * 78)
print("CATEGORY BREAKDOWN")
print("-" * 78)
all_cats = sorted({c for r in results.values() for c in r["categories"]})
header = "Category".ljust(18) + "".join(f"{n[:14]:>14}" for n in results)
print(header)
print("-" * len(header))
for cat in all_cats:
    row = cat.ljust(18) + "".join(f"{r['categories'].get(cat, 0):>14}" for r in results.values())
    print(row)

for name, r in results.items():
    print()
    print("=" * 78)
    print(f"{name.upper()}  —  {r['april_count']} mentions in April {TARGET_YEAR}")
    print("=" * 78)
    if r["sources"]:
        print("Top sources:", ", ".join(f"{s} ({n})" for s, n in r["sources"]))
    if not r["april"]:
        print("(No April articles found in RSS feed.)")
        continue
    print()
    print("Headlines (most recent first):")
    for a in sorted(r["april"], key=lambda x: x["published"], reverse=True):
        date = a["published"].strftime("%b %d")
        cat = categorize(a["title"])
        src = a["source"][:24] if a["source"] else "—"
        print(f"  {date}  [{cat:<14}] {src:<24} {a['title']}")
