#!/usr/bin/env python3
"""Classify Sunsure FY26 coverage into Press Release / Authored / Feature buckets.
Heuristic-based — no LLM. Outputs counts + samples for KRA reporting."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
data = json.loads((ROOT / "sov_data.json").read_text())

PR_VERBS = re.compile(
    r"\b(signs?|secures?|commissions?|raises?|launches?|inaugurat\w*|announces?|"
    r"partners?|inks?|wins?|awarded|completes?|acquires?|enters?|opens?|deploys?|"
    r"to\s+supply|to\s+procure|bags?|signs?-up)\b",
    re.I,
)
BYLINE = re.compile(r"^\s*by\s+[A-Z][a-z]+\s+[A-Z][a-z]+", re.I)
OPINION_SECTIONS = {"opinion", "views", "op-ed", "perspective", "guest column"}


def classify(article: dict) -> str:
    title = article.get("title") or ""
    snippet = (article.get("snippet") or "")[:120]
    source = (article.get("source") or "").lower()

    # 1) Authored — byline or opinion section
    if BYLINE.match(snippet) or "by " in snippet[:30].lower() and "energy" not in snippet[:30].lower():
        # second condition is loose — verify by checking snippet starts with author name pattern
        if re.match(r"^\s*by\s+[a-zA-Z]+\s+[a-zA-Z]+", snippet, re.I):
            return "authored"
    if any(s in source for s in OPINION_SECTIONS):
        return "authored"
    if re.search(r"\bop-?ed\b|\bopinion\b|\bviews\b", title, re.I):
        return "authored"

    # 2) Press release — action-verb headline
    if PR_VERBS.search(title):
        return "press_release"

    # 3) Feature — everything else
    return "feature"


def cluster_releases(articles: list[dict]) -> list[list[dict]]:
    """Group press-release articles by similar first 5 meaningful words.
    Each cluster represents ONE underlying announcement."""
    stop = {"the", "a", "an", "of", "for", "in", "to", "and", "with", "on", "by"}
    clusters: dict[str, list[dict]] = defaultdict(list)
    for a in articles:
        words = re.findall(r"[a-z0-9]+", a["title"].lower())
        key_words = [w for w in words if w not in stop][:5]
        key = " ".join(key_words)
        clusters[key].append(a)
    return list(clusters.values())


# Process Sunsure articles for FY26 (Apr 2025 to Mar 2026)
fy_months = [m["label"] for m in data["months"]]
sunsure_articles = []
for m in fy_months:
    sunsure_articles.extend(data["data"]["Sunsure"][m])

print(f"Total Sunsure FY26 articles in pool: {len(sunsure_articles)}")
print()

buckets: dict[str, list[dict]] = defaultdict(list)
for a in sunsure_articles:
    buckets[classify(a)].append(a)

pr_articles = buckets["press_release"]
authored = buckets["authored"]
features = buckets["feature"]

# Cluster press releases to get unique announcement count
pr_clusters = cluster_releases(pr_articles)
unique_announcements = len(pr_clusters)
total_pr_pickups = sum(len(c) for c in pr_clusters)
avg_pickups = total_pr_pickups / unique_announcements if unique_announcements else 0

print("=" * 70)
print("SUNSURE ENERGY — FY26 COVERAGE CLASSIFICATION")
print("April 2025 – March 2026")
print("=" * 70)
print()
print(f"📢 Press Releases (Market Announcements)")
print(f"   • {unique_announcements} unique announcements")
print(f"   • {total_pr_pickups} total media pickups (avg {avg_pickups:.1f} outlets per release)")
print()
print(f"✍️  Authored Articles")
print(f"   • {len(authored)} bylined / opinion pieces")
print()
print(f"📰 Media Features")
print(f"   • {len(features)} editorial features / interviews / mentions")
print()
print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(f"   TOTAL ARTICLES: {len(sunsure_articles)}")
print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print()

# Show samples
print("=" * 70)
print("📢 PRESS RELEASES — UNIQUE ANNOUNCEMENTS (sample title from each cluster)")
print("=" * 70)
print()
pr_clusters_sorted = sorted(pr_clusters, key=lambda c: len(c), reverse=True)
for i, cluster in enumerate(pr_clusters_sorted, 1):
    rep = max(cluster, key=lambda a: len(a["title"]))
    pickups = len(cluster)
    date = rep.get("published", "")[:10] if rep.get("published") else ""
    print(f"  {i:2d}. [{pickups} pickup{'s' if pickups != 1 else ''}] {date}  {rep['title'][:90]}")

print()
print("=" * 70)
print("✍️  AUTHORED ARTICLES")
print("=" * 70)
print()
if authored:
    for i, a in enumerate(authored, 1):
        date = a.get("published", "")[:10] if a.get("published") else ""
        src = a.get("source") or "—"
        print(f"  {i}. {date}  [{src[:25]}] {a['title'][:100]}")
else:
    print("  (None detected. See note in dashboard about authored article detection limitations.)")

print()
print("=" * 70)
print("📰 MEDIA FEATURES (sample)")
print("=" * 70)
print()
features_sorted = sorted(features, key=lambda a: a.get("published", "") or "", reverse=True)
for i, a in enumerate(features_sorted[:15], 1):
    date = a.get("published", "")[:10] if a.get("published") else ""
    src = a.get("source") or "—"
    print(f"  {i:2d}. {date}  [{src[:25]:<25}] {a['title'][:90]}")

if len(features) > 15:
    print(f"  ... and {len(features) - 15} more")

# Save structured output for dashboard tab
out = {
    "fy_label": "FY26 (Apr 2025 – Mar 2026)",
    "total_articles": len(sunsure_articles),
    "press_releases": {
        "unique_count": unique_announcements,
        "total_pickups": total_pr_pickups,
        "avg_pickups_per_release": round(avg_pickups, 1),
        "clusters": [
            {
                "representative_title": max(c, key=lambda a: len(a["title"]))["title"],
                "pickups": len(c),
                "date": (max(c, key=lambda a: a.get("published", "") or "")["published"] or "")[:10],
                "outlets": sorted(set(a.get("source") or "—" for a in c)),
            }
            for c in pr_clusters_sorted
        ],
    },
    "authored": {
        "count": len(authored),
        "articles": [{"title": a["title"], "source": a.get("source"),
                      "date": (a.get("published") or "")[:10], "url": a["url"]}
                     for a in authored],
    },
    "features": {
        "count": len(features),
        "articles": [{"title": a["title"], "source": a.get("source"),
                      "date": (a.get("published") or "")[:10], "url": a["url"]}
                     for a in features_sorted],
    },
}

(ROOT / "kra_classification.json").write_text(json.dumps(out, indent=2, default=str))
print(f"\n✅ Saved: kra_classification.json")
