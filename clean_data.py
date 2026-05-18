#!/usr/bin/env python3
"""Remove Google News false positives from sov_data*.json files.
Keeps an article only if the company's name actually appears in title or snippet.
Outputs *_clean.json versions and prints a per-company noise report."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent

# Each entry: list of plain substrings OR compiled regex patterns.
# An article passes if ANY item matches title+snippet (case-insensitive).
# For ReNew: \brenew\b catches "ReNew" as a standalone word without
# matching "renewable", "renewables", "renewal", etc.
MATCH_PATTERNS: dict[str, list] = {
    "Sunsure":        ["sunsure"],
    "ReNew":          [re.compile(r"\brenew\b", re.I)],
    "Cleanmax":       ["cleanmax", "clean max"],
    "Ampin":          ["ampin"],
    "Gentari/Amplus": ["gentari", "amplus"],
    "Hexa Climate":   ["hexa climate"],
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

    print(f"\n{'='*60}")
    print(f"File: {path.name}")
    print(f"{'='*60}")
    print(f"{'Company':<22} {'Before':>7} {'After':>7} {'Removed':>9} {'Noise%':>8}")
    print(f"{'-'*55}")

    for company in companies:
        terms = MATCH_PATTERNS.get(company, [])
        before = 0
        after = 0
        for m in months:
            arts = data["data"][company].get(m, [])
            before += len(arts)
            if terms:
                clean = [a for a in arts if is_match(a, terms)]
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
        print(f"{company:<22} {before:>7} {after:>7} {removed:>9} {noise_pct:>7.1f}%")

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
