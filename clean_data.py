#!/usr/bin/env python3
"""Remove Google News false positives from sov_data*.json files.
Keeps an article if the company's name appears in title or snippet, or if it
covers the same story as one that does (body mentions, see link_story_articles).
Outputs *_clean.json versions and prints a per-company noise report."""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent

# Each entry: list of plain substrings OR compiled regex patterns.
# An article passes if ANY item matches title+snippet (case-insensitive).
# For ReNew: \brenew\b catches "ReNew" as a standalone word without
# matching "renewable", "renewables", "renewal", etc.
MATCH_PATTERNS: dict[str, list] = {
    # Case-sensitive so "many sunsure about..." (typo for "unsure") doesn't match
    "Sunsure":        [re.compile(r"\b(Sunsure|SUNSURE)\b")],
    "ReNew":          [re.compile(r"\brenew\b", re.I)],
    "Cleanmax":       ["cleanmax", "clean max"],
    "Ampin":          ["ampin"],
    "Gentari/Amplus": ["gentari", "amplus"],
    "Hexa Climate":   ["hexa climate"],
    "Serentica":      ["serentica"],
}


def is_match(article: dict, patterns: list) -> bool:
    haystack = (
        (article.get("title") or "") + " " + (article.get("snippet") or "")
    )
    for p in patterns:
        if isinstance(p, re.Pattern):
            if p.search(haystack):
                return True
        else:
            if p.lower() in haystack.lower():
                return True
    return False


# Story linking: Google News searches are exact-phrase, so an article it returns
# for "Sunsure Energy" usually names Sunsure in the body even when the headline
# doesn't ("Amazon to invest $7 billion in India..."). Such an article is kept
# when its headline shares a distinctive term that dominates the company's own
# headlines around that date: in at least STORY_MIN_KEPT of them, and at least
# STORY_MIN_SHARE of those published within STORY_WINDOW_DAYS.
STORY_WINDOW_DAYS = 4
STORY_MIN_KEPT = 3
STORY_MIN_SHARE = 0.3
STORY_MAX_DF = 0.02  # a term in >2% of all headlines is too generic to link on
STORY_STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "its", "via", "over", "after",
    "new", "plans", "announces", "takes", "wins", "signs", "inks", "secures",
    "stock", "stocks", "share", "shares", "buy", "sell", "nse", "bse", "ipo",
    "ipos", "today", "price", "target", "profit", "revenue", "results", "check",
}


def _headline(article: dict) -> str:
    # Drop Google News' trailing " - Source"
    return re.sub(r"\s+-\s+[^-]+$", "", article.get("title") or "")


def _terms(article: dict) -> set[str]:
    words = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z&']{2,}", _headline(article))}
    return words - STORY_STOPWORDS


def _pub_date(article: dict):
    try:
        return datetime.fromisoformat((article.get("published") or "")[:19]).date()
    except ValueError:
        return None


def headline_doc_freq(articles: list[dict]) -> dict[str, float]:
    df = Counter()
    for a in articles:
        df.update(_terms(a))
    n = len(articles) or 1
    return {t: c / n for t, c in df.items()}


def link_story_articles(kept: list[dict], dropped: list[dict], doc_freq: dict[str, float],
                        own_terms: set[str]) -> list[dict]:
    """Return the articles in `dropped` that cover a story already in `kept`."""
    kept_dated = [(_pub_date(a), _terms(a)) for a in kept]
    linked = []
    for a in dropped:
        d = _pub_date(a)
        if d is None:
            continue
        nearby = [t for k, t in kept_dated if k and abs((d - k).days) <= STORY_WINDOW_DAYS]
        for term in sorted(_terms(a) - own_terms):
            if doc_freq.get(term, 0) > STORY_MAX_DF:
                continue
            hits = sum(term in t for t in nearby)
            if hits >= STORY_MIN_KEPT and hits / len(nearby) >= STORY_MIN_SHARE:
                linked.append({**a, "match": f"story:{term}"})
                break
    return linked


def clean_dataset(path: Path) -> Path:
    data = json.loads(path.read_text())
    # Drop companies not in MATCH_PATTERNS (removed from tracker)
    companies = [c for c in data["companies"] if c in MATCH_PATTERNS]
    data["companies"] = companies
    for c in list(data["data"]):
        if c not in companies:
            del data["data"][c]
            data["highlights"].pop(c, None)
    months = [m["label"] for m in data["months"]]
    doc_freq = headline_doc_freq(
        [a for c in companies for m in months for a in data["data"][c].get(m, [])]
    )

    print(f"\n{'='*60}")
    print(f"File: {path.name}")
    print(f"{'='*60}")
    print(f"{'Company':<22} {'Before':>7} {'After':>7} {'Linked':>7} {'Removed':>9} {'Noise%':>8}")
    print(f"{'-'*63}")

    for company in companies:
        terms = MATCH_PATTERNS.get(company, [])
        own_terms = {w.lower() for w in re.findall(r"[A-Za-z]+", company)}
        before = 0
        after = 0
        linked_total = 0
        for m in months:
            arts = data["data"][company].get(m, [])
            before += len(arts)
            if terms:
                clean = [a for a in arts if is_match(a, terms)]
                dropped = [a for a in arts if not is_match(a, terms)]
                linked = link_story_articles(clean, dropped, doc_freq, own_terms)
                clean += linked
                linked_total += len(linked)
            else:
                clean = arts
            data["data"][company][m] = clean
            after += len(clean)

            # Rebuild highlight for this month from cleaned articles
            clean_arts = data["data"][company][m]
            if clean_arts:
                from collections import defaultdict
                clusters: dict[str, list] = defaultdict(list)
                for a in clean_arts:
                    key = " ".join(a["title"].lower().split()[:6])
                    clusters[key].append(a)
                biggest = max(clusters.values(), key=len)
                data["highlights"][company][m] = max(biggest, key=lambda a: len(a["title"]))
            else:
                data["highlights"][company][m] = None

        removed = before - after
        noise_pct = removed / before * 100 if before else 0
        print(f"{company:<22} {before:>7} {after:>7} {linked_total:>7} {removed:>9} {noise_pct:>7.1f}%")

    out_path = path.parent / path.name.replace(".json", "_clean.json")
    out_path.write_text(json.dumps(data, indent=2, default=str))
    print(f"\n✅ Saved: {out_path.name}  ({out_path.stat().st_size // 1024} KB)")
    return out_path


if __name__ == "__main__":
    for fname in ["sov_data_fy25.json", "sov_data.json"]:
        p = ROOT / fname
        if p.exists():
            clean_dataset(p)
        else:
            print(f"⚠️  {fname} not found, skipping")
