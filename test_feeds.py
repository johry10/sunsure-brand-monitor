#!/usr/bin/env python3
"""Validate candidate RSS feeds: check each returns parseable entries with recent dates."""
from __future__ import annotations
import feedparser
from datetime import datetime, timedelta
from time import mktime

CANDIDATES = [
    ("ET EnergyWorld", "https://energy.economictimes.indiatimes.com/rss/topstories"),
    ("Mercom India", "https://www.mercomindia.com/feed"),
    ("PV Magazine India", "https://www.pv-magazine-india.com/feed/"),
    ("Saur Energy", "https://www.saurenergy.com/feed"),
    ("SolarQuarter", "https://solarquarter.com/feed/"),
    ("Energetica India", "https://www.energetica-india.net/rss/all-news"),
    ("Business Standard - Companies", "https://www.business-standard.com/rss/companies-101.rss"),
    ("Mint - Companies", "https://www.livemint.com/rss/companies"),
    ("PIB Power & New Energy", "https://pib.gov.in/rss/lreleases.aspx?ministryid=28"),
    ("ET Auto", "https://auto.economictimes.indiatimes.com/rss/topstories"),
    ("ET Manufacturing", "https://manufacturing.economictimes.indiatimes.com/rss/topstories"),
    ("Renewables Now", "https://renewablesnow.com/news/feed/"),
    ("PV Tech", "https://www.pv-tech.org/feed/"),
    ("Reuters India", "https://www.reutersagency.com/feed/?best-regions=india&post_type=best"),
    ("Devdiscourse Energy", "https://www.devdiscourse.com/rss/category/business/energy"),
]

cutoff = datetime.now() - timedelta(days=14)
print(f"{'Feed':<35} {'Entries':>8} {'Recent':>8}  {'Status'}")
print("-" * 78)

working = []
for name, url in CANDIDATES:
    try:
        d = feedparser.parse(url)
        n = len(d.entries)
        if d.bozo and n == 0:
            print(f"{name:<35} {0:>8}    n/a  ❌ parse error: {str(d.bozo_exception)[:30]}")
            continue
        recent = 0
        for e in d.entries:
            if e.get("published_parsed"):
                try:
                    pub = datetime.fromtimestamp(mktime(e.published_parsed))
                    if pub > cutoff:
                        recent += 1
                except Exception:
                    pass
        if n > 0 and recent > 0:
            print(f"{name:<35} {n:>8} {recent:>8}  ✅")
            working.append((name, url))
        elif n > 0:
            print(f"{name:<35} {n:>8} {recent:>8}  ⚠️  no recent items")
        else:
            print(f"{name:<35} {n:>8} {0:>8}  ❌ empty feed")
    except Exception as e:
        print(f"{name:<35} {'-':>8} {'-':>8}  ❌ {str(e)[:40]}")

print()
print(f"Working: {len(working)} of {len(CANDIDATES)}")
print()
print("Feeds to add to config.yaml:")
for name, url in working:
    print(f'  - name: "{name}"')
    print(f'    url: "{url}"')
