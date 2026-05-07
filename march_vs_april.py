#!/usr/bin/env python3
"""March 2026 vs April 2026 coverage comparison. Outputs a markdown report."""
from __future__ import annotations

import urllib.parse
from collections import Counter
from datetime import datetime
from pathlib import Path
from time import mktime

import feedparser

ROOT = Path(__file__).parent

COMPANIES = {
    "Sunsure Energy": ["Sunsure Energy", "Sunsure Solar"],
    "ReNew": ["ReNew Power"],
    "Ampin Energy": ["Ampin Energy", "AMPIN Energy"],
    "Cleanmax": ["Cleanmax Solar", "Cleanmax Enviro"],
    "Gentari": ["Gentari"],
}


def google_news_url(q: str) -> str:
    return (
        f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}"
        f"&hl=en-IN&gl=IN&ceid=IN:en"
    )


def fetch_for(queries: list[str]) -> list[dict]:
    seen = set()
    out = []
    for q in queries:
        d = feedparser.parse(google_news_url(f'"{q}"'))
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
                    pass
            out.append({
                "title": e.get("title", "").strip(),
                "url": link,
                "source": (e.get("source", {}) or {}).get("title") or "",
                "published": pub,
            })
    return out


def in_month(a: dict, year: int, month: int) -> bool:
    return bool(a["published"]) and a["published"].year == year and a["published"].month == month


def categorize(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["ppa", "power purchase", "signs", "supply", "agreement", "deal"]):
        return "Deal/PPA"
    if any(k in t for k in ["funding", "debt", "raise", "loan", "crore", "million", "billion", "ipo", "stake"]):
        return "Financial"
    if any(k in t for k in ["commission", "operational", "starts", "online", "go-live", "inaugurat"]):
        return "Project go-live"
    if any(k in t for k in ["acquire", "acquisition", "merger"]):
        return "M&A"
    if any(k in t for k in ["ceo", "appoint", "hires", "joins", "exits", "managing director"]):
        return "Leadership"
    if any(k in t for k in ["tender", "bid", "auction", "secured", "wins", "awarded"]):
        return "Tender/Bid"
    if any(k in t for k in ["manufactur", "factory", "plant", "facility"]):
        return "Manufacturing"
    return "Other"


def fmt_pct(num: int, denom: int) -> str:
    if denom == 0:
        return "n/a"
    return f"{(num/denom)*100:+.0f}%"


def fmt_delta(new: int, old: int) -> str:
    d = new - old
    return f"{'+' if d >= 0 else ''}{d}"


# Fetch all
print("Fetching feeds...")
data: dict[str, dict] = {}
for name, queries in COMPANIES.items():
    print(f"  • {name}...", end=" ", flush=True)
    arts = fetch_for(queries)
    march = [a for a in arts if in_month(a, 2026, 3)]
    april = [a for a in arts if in_month(a, 2026, 4)]
    data[name] = {
        "total": len(arts),
        "march": march,
        "april": april,
        "march_cats": Counter(categorize(a["title"]) for a in march),
        "april_cats": Counter(categorize(a["title"]) for a in april),
        "march_sources": Counter(a["source"] for a in march if a["source"]).most_common(5),
        "april_sources": Counter(a["source"] for a in april if a["source"]).most_common(5),
    }
    print(f"{len(arts)} total ({len(march)} March, {len(april)} April)")

# Build markdown
ts = datetime.now().strftime("%Y-%m-%d %H:%M")
lines: list[str] = []
lines.append("# Sunsure Energy — Media Coverage Comparison")
lines.append(f"## March 2026 vs April 2026 (Apr 1–25)")
lines.append("")
lines.append(f"*Generated: {ts}  |  Source: Google News RSS  |  Region: India*")
lines.append("")
lines.append("---")
lines.append("")

# Scoreboard
lines.append("## 1. Headline Scoreboard")
lines.append("")
lines.append("| Company | March | April (1–25) | Δ | April daily avg | March daily avg |")
lines.append("|---|---:|---:|---:|---:|---:|")
for name, r in data.items():
    m, a = len(r["march"]), len(r["april"])
    md_avg = m / 31
    ap_avg = a / 25
    lines.append(f"| **{name}** | {m} | {a} | {fmt_delta(a, m)} | {ap_avg:.2f}/day | {md_avg:.2f}/day |")
lines.append("")
lines.append("> Note: April is 25 days vs March's 31, so daily averages give a fairer rate-of-coverage view.")
lines.append("")

# Category breakdown
lines.append("## 2. Coverage Category Breakdown")
lines.append("")
all_cats = sorted({c for r in data.values() for c in (list(r["march_cats"]) + list(r["april_cats"]))})
for period_key, period_label in [("march_cats", "March 2026"), ("april_cats", "April 2026 (1–25)")]:
    lines.append(f"### {period_label}")
    lines.append("")
    header = "| Category | " + " | ".join(data.keys()) + " |"
    sep = "|---|" + "---:|" * len(data)
    lines.append(header)
    lines.append(sep)
    for cat in all_cats:
        row = f"| {cat} | " + " | ".join(str(data[n][period_key].get(cat, 0)) for n in data) + " |"
        lines.append(row)
    lines.append("")

# Per company
lines.append("## 3. Per-Company Detail")
lines.append("")

for name, r in data.items():
    m, a = len(r["march"]), len(r["april"])
    lines.append(f"### {name}")
    lines.append("")
    lines.append(f"**March: {m} mentions  |  April (1–25): {a} mentions  |  Δ: {fmt_delta(a, m)}**")
    lines.append("")
    if r["march_sources"]:
        lines.append("**Top March sources:** " + ", ".join(f"{s} ({n})" for s, n in r["march_sources"]))
        lines.append("")
    if r["april_sources"]:
        lines.append("**Top April sources:** " + ", ".join(f"{s} ({n})" for s, n in r["april_sources"]))
        lines.append("")

    if r["march"]:
        lines.append("**March headlines:**")
        lines.append("")
        for art in sorted(r["march"], key=lambda x: x["published"], reverse=True):
            d = art["published"].strftime("%b %d")
            cat = categorize(art["title"])
            src = art["source"] or "—"
            lines.append(f"- `{d}` *[{cat}]* **{src}** — {art['title']}")
        lines.append("")
    else:
        lines.append("*No March articles found.*")
        lines.append("")

    if r["april"]:
        lines.append("**April headlines:**")
        lines.append("")
        for art in sorted(r["april"], key=lambda x: x["published"], reverse=True):
            d = art["published"].strftime("%b %d")
            cat = categorize(art["title"])
            src = art["source"] or "—"
            lines.append(f"- `{d}` *[{cat}]* **{src}** — {art['title']}")
        lines.append("")
    else:
        lines.append("*No April articles found.*")
        lines.append("")

# Caveats
lines.append("## 4. Caveats")
lines.append("")
lines.append("- **Google News RSS limit**: ~100 articles per query. Companies with very high coverage may have a tail of older articles cut off.")
lines.append("- **No paywalled coverage**: Bloomberg, Mint Premium, FT not included.")
lines.append("- **No social or print**: LinkedIn posts, X mentions, print newspaper coverage not captured.")
lines.append("- **No relevance filtering**: A few articles may be tangential mentions rather than primary subjects (a real Claude classification step would filter these).")
lines.append("- **No sentiment analysis**: Volume only, not tone.")
lines.append("")

report = "\n".join(lines)
out_path = ROOT / "march_vs_april_2026.md"
out_path.write_text(report)
print(f"\nReport saved: {out_path}")
print(f"Word count: {len(report.split())}")
