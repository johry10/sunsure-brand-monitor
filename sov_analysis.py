#!/usr/bin/env python3
"""Share of Voice analysis: Sunsure vs competitors, March vs April 2026.
Pulls Google News + 8 industry RSS feeds, dedupes, computes SOV %."""
from __future__ import annotations

import re
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from time import mktime

import feedparser
import yaml

ROOT = Path(__file__).parent

# Each company → list of (display_name, regex pattern matching title/snippet)
COMPANIES: dict[str, list[str]] = {
    "Sunsure":      [r"\bsunsure\b"],
    "ReNew":        [r"\brenew\s+(power|energy global|energy)\b", r"\brenew\b(?=\s+(commission|signs|secures|raises|acquires))"],
    "Ampin":        [r"\bampin\b", r"\bamp\s+energy\b"],
    "Cleanmax":     [r"\bcleanmax\b", r"\bclean\s*max\b"],
    "Gentari":      [r"\bgentari\b"],
}

# Google News search queries per company (used to fetch RSS feeds)
GOOGLE_QUERIES: dict[str, list[str]] = {
    "Sunsure":  ["Sunsure Energy", "Sunsure Solar"],
    "ReNew":    ["ReNew Power", "ReNew Energy Global"],
    "Ampin":    ["Ampin Energy", "AMPIN Solar"],
    "Cleanmax": ["Cleanmax Solar", "Cleanmax Enviro"],
    "Gentari":  ["Gentari renewable"],
}


def google_news_url(q: str) -> str:
    return (f"https://news.google.com/rss/search?q={urllib.parse.quote(f'\"{q}\"')}"
            f"&hl=en-IN&gl=IN&ceid=IN:en")


def parse_pub(entry) -> datetime | None:
    if entry.get("published_parsed"):
        try:
            return datetime.fromtimestamp(mktime(entry.published_parsed))
        except Exception:
            return None
    return None


def fetch_feed(url: str, source_label: str) -> list[dict]:
    out = []
    try:
        d = feedparser.parse(url)
    except Exception:
        return out
    for e in d.entries:
        link = e.get("link", "")
        if not link:
            continue
        out.append({
            "title": e.get("title", "").strip(),
            "url": link,
            "source": (e.get("source", {}) or {}).get("title") or source_label,
            "published": parse_pub(e),
            "snippet": (e.get("summary", "") or "")[:600],
        })
    return out


def detect_companies(article: dict) -> list[str]:
    """Return list of company names whose patterns match this article."""
    text = f"{article['title']} {article['snippet']}".lower()
    matched = []
    for company, patterns in COMPANIES.items():
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                matched.append(company)
                break
    return matched


def in_month(a: dict, year: int, month: int) -> bool:
    return bool(a["published"]) and a["published"].year == year and a["published"].month == month


def categorize(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["ppa", "power purchase", "signs", "supply agreement", "deal"]):
        return "Deal/PPA"
    if any(k in t for k in ["funding", "debt", "raise", "loan", "crore", "stake", "ipo"]):
        return "Financial"
    if any(k in t for k in ["commission", "operational", "starts", "online", "inaugurat"]):
        return "Project go-live"
    if any(k in t for k in ["acquir", "acquisition", "merger"]):
        return "M&A"
    if any(k in t for k in ["ceo", "appoint", "joins", "managing director", "promoted"]):
        return "Leadership"
    if any(k in t for k in ["tender", "bid", "auction", "wins", "awarded", "secured"]):
        return "Tender/Bid"
    if any(k in t for k in ["manufactur", "factory", "plant", "facility", "module"]):
        return "Manufacturing"
    return "Other"


# Load config to reuse extra_feeds
cfg = yaml.safe_load((ROOT / "config.yaml").read_text())

# === Fetch everything ===
print("Phase 1: Fetching Google News (per company)...")
all_articles: dict[str, dict] = {}  # url -> article
for company, queries in GOOGLE_QUERIES.items():
    for q in queries:
        for art in fetch_feed(google_news_url(q), f"Google News [{company}]"):
            if art["url"] not in all_articles:
                all_articles[art["url"]] = art
    print(f"  • {company}: pool now {len(all_articles)} unique URLs")

print("\nPhase 2: Fetching industry RSS feeds...")
for feed in cfg.get("extra_feeds", []):
    before = len(all_articles)
    for art in fetch_feed(feed["url"], feed["name"]):
        if art["url"] not in all_articles:
            all_articles[art["url"]] = art
    added = len(all_articles) - before
    print(f"  • {feed['name']}: +{added} new (pool now {len(all_articles)})")

print(f"\nTotal unique articles in pool: {len(all_articles)}")

# === Detect mentions ===
print("\nPhase 3: Detecting company mentions...")
mentions_by_month: dict[tuple[int, int], dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
articles_by_company_month: dict[tuple[int, int, str], list[dict]] = defaultdict(list)

march_total = 0
april_total = 0
march_by_company: dict[str, int] = Counter()
april_by_company: dict[str, int] = Counter()
march_by_company_articles: dict[str, list[dict]] = defaultdict(list)
april_by_company_articles: dict[str, list[dict]] = defaultdict(list)

for art in all_articles.values():
    if not art["published"]:
        continue
    companies = detect_companies(art)
    if not companies:
        continue
    if in_month(art, 2026, 3):
        march_total += 1
        for c in companies:
            march_by_company[c] += 1
            march_by_company_articles[c].append(art)
    elif in_month(art, 2026, 4):
        april_total += 1
        for c in companies:
            april_by_company[c] += 1
            april_by_company_articles[c].append(art)

print(f"  • March 2026: {march_total} unique articles mentioning at least one company")
print(f"  • April 2026: {april_total} unique articles mentioning at least one company")

# === Compute SOV ===
march_total_mentions = sum(march_by_company.values())
april_total_mentions = sum(april_by_company.values())


def sov(count: int, total: int) -> float:
    return (count / total * 100) if total else 0.0


# === Build markdown report ===
ts = datetime.now().strftime("%Y-%m-%d %H:%M")
lines: list[str] = []
lines.append("# Sunsure Energy — Share of Voice Analysis")
lines.append("## March 2026 vs April 2026 (Apr 1–25)")
lines.append("")
lines.append(f"*Generated: {ts}  |  Sources: Google News + 8 industry RSS feeds  |  Method: free RSS only, no LLM*")
lines.append("")
lines.append("---")
lines.append("")

# Methodology
lines.append("## Methodology")
lines.append("")
lines.append(f"- **Pool**: {len(all_articles)} unique articles across Google News and industry RSS feeds")
lines.append("- **Detection**: regex match on company name in title or article snippet")
lines.append("- **Multi-mention articles**: counted once for each company mentioned (e.g., 'Sunsure beats ReNew in tender' counts for both)")
lines.append(f"- **March denominator**: {march_total_mentions} total company-mentions across {march_total} unique articles")
lines.append(f"- **April denominator**: {april_total_mentions} total company-mentions across {april_total} unique articles")
lines.append("")

# Headline SOV table
lines.append("## 1. Share of Voice — Headline Numbers")
lines.append("")
lines.append("| Company | March SOV | April SOV | Δ SOV (pp) | March mentions | April mentions | Δ count |")
lines.append("|---|---:|---:|---:|---:|---:|---:|")
for company in COMPANIES:
    m, a = march_by_company.get(company, 0), april_by_company.get(company, 0)
    msov = sov(m, march_total_mentions)
    asov = sov(a, april_total_mentions)
    delta_sov = asov - msov
    delta_count = a - m
    lines.append(
        f"| **{company}** | {msov:.1f}% | {asov:.1f}% | {delta_sov:+.1f} | {m} | {a} | {delta_count:+d} |"
    )
lines.append("")
lines.append("> SOV = company's mentions ÷ all-tracked-companies' mentions in that month.  ")
lines.append("> Δ SOV is in **percentage points** (pp), not relative %.")
lines.append("")

# Daily rate normalization
lines.append("## 2. Normalized Daily Rate (March = 31 days, April = 25 days)")
lines.append("")
lines.append("| Company | March mentions/day | April mentions/day | Δ rate |")
lines.append("|---|---:|---:|---:|")
for company in COMPANIES:
    m, a = march_by_company.get(company, 0), april_by_company.get(company, 0)
    md, ad = m / 31, a / 25
    lines.append(f"| **{company}** | {md:.2f} | {ad:.2f} | {ad - md:+.2f} |")
lines.append("")

# Visual SOV (text bar chart)
lines.append("## 3. Visual SOV Comparison")
lines.append("")
lines.append("```")
lines.append("MARCH 2026")
for company in COMPANIES:
    pct = sov(march_by_company.get(company, 0), march_total_mentions)
    bar = "█" * int(pct / 2)  # 1 char = 2%
    lines.append(f"{company:<10} {bar:<25} {pct:>5.1f}%  ({march_by_company.get(company, 0)} mentions)")
lines.append("")
lines.append("APRIL 2026 (1-25)")
for company in COMPANIES:
    pct = sov(april_by_company.get(company, 0), april_total_mentions)
    bar = "█" * int(pct / 2)
    lines.append(f"{company:<10} {bar:<25} {pct:>5.1f}%  ({april_by_company.get(company, 0)} mentions)")
lines.append("```")
lines.append("")

# Source breakdown for Sunsure
lines.append("## 4. Sunsure's Coverage Sources")
lines.append("")
for label, articles in [("March", march_by_company_articles["Sunsure"]),
                        ("April", april_by_company_articles["Sunsure"])]:
    if not articles:
        continue
    sources = Counter(a["source"] for a in articles).most_common(10)
    lines.append(f"### {label} 2026")
    lines.append("")
    lines.append("| Source | Articles |")
    lines.append("|---|---:|")
    for s, n in sources:
        lines.append(f"| {s} | {n} |")
    lines.append("")

# Category breakdown
lines.append("## 5. Sunsure's Coverage by Category")
lines.append("")
lines.append("| Category | March | April |")
lines.append("|---|---:|---:|")
m_cats = Counter(categorize(a["title"]) for a in march_by_company_articles["Sunsure"])
a_cats = Counter(categorize(a["title"]) for a in april_by_company_articles["Sunsure"])
all_cats = sorted(set(m_cats) | set(a_cats))
for cat in all_cats:
    lines.append(f"| {cat} | {m_cats.get(cat, 0)} | {a_cats.get(cat, 0)} |")
lines.append("")

# Headline lists
lines.append("## 6. Sunsure Headlines")
lines.append("")
for label, articles in [("### March 2026", march_by_company_articles["Sunsure"]),
                        ("### April 2026 (1–25)", april_by_company_articles["Sunsure"])]:
    lines.append(label)
    lines.append("")
    if not articles:
        lines.append("*No articles found.*")
        lines.append("")
        continue
    for a in sorted(articles, key=lambda x: x["published"], reverse=True):
        d = a["published"].strftime("%b %d")
        cat = categorize(a["title"])
        src = a["source"] or "—"
        lines.append(f"- `{d}` *[{cat}]* **{src}** — {a['title']}")
    lines.append("")

# Caveats
lines.append("## 7. Caveats & Notes")
lines.append("")
lines.append("- **Google News RSS cap (~100 articles per query)**: For very high-coverage companies (e.g., ReNew), the most recent ~100 articles may not span both months fully. Industry RSS feeds partially compensate.")
lines.append("- **No paywalled coverage**: Bloomberg, FT, Mint Premium content is excluded.")
lines.append("- **No social or print/broadcast**: LinkedIn, X, newspaper print, TV not captured.")
lines.append("- **Regex-based detection**: Strict word boundary matching. False positives are rare; false negatives possible if the publication uses an alternate name.")
lines.append("- **Multi-mention counting**: An article naming both Sunsure and ReNew counts toward each company's mentions but only once toward the denominator (article count).")
lines.append("- **No sentiment analysis in this report** — added in next iteration via VADER.")
lines.append("")

out_path = ROOT / "sov_march_vs_april_2026.md"
out_path.write_text("\n".join(lines))
print(f"\n✅ Report saved: {out_path}")
print(f"   {len(lines)} lines, {sum(len(l) for l in lines)} chars")
