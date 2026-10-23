#!/usr/bin/env python3
"""Twice-daily email digest of new coverage for Sunsure + competitors.

Free sources only (Google News RSS, industry RSS, GDELT, Bing) and VADER for
sentiment — no LLM API. Articles already emailed are remembered in
digest_seen.json (committed back by the GitHub Action, since runners are
stateless).

Env vars:
  GMAIL_USER          sending Gmail address
  GMAIL_APP_PASSWORD  16-char Gmail App Password
  DIGEST_TO           comma-separated recipients

Usage:
  python digest.py              # send email
  python digest.py --dry-run    # write digest_preview.html, don't send or mark seen
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from time import mktime

import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from clean_data import MATCH_PATTERNS, is_match
from collect_data import COMPANIES
from industry_feeds import fetch_industry_articles
from supplementary_feeds import fetch_supplementary_articles

ROOT = Path(__file__).parent
SEEN_PATH = ROOT / "digest_seen.json"
SOV_PATH = ROOT / "sov_data_clean.json"
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "")
LOOKBACK_HOURS = 36       # overlap between runs; seen-file prevents repeats
SEEN_RETENTION_DAYS = 30
IST = timezone(timedelta(hours=5, minutes=30))
BRAND = "#FD3A20"

TIER1 = {
    "economic times", "the economic times", "et energyworld", "mint", "livemint",
    "business standard", "the hindu businessline", "hindu businessline",
    "the hindu", "financial express", "the financial express", "moneycontrol",
    "reuters", "bloomberg", "cnbc tv18", "cnbctv18.com", "ndtv profit",
    "times of india", "the times of india", "hindustan times", "business today",
    "mercomindia.com", "pv magazine india", "pv tech",
}


def google_news_recent(query: str) -> list[dict]:
    q = urllib.parse.quote(f'"{query}" when:2d')
    url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
    out = []
    for e in feedparser.parse(url).entries:
        if not e.get("link"):
            continue
        pub = None
        if e.get("published_parsed"):
            pub = datetime.fromtimestamp(mktime(e.published_parsed), timezone.utc).isoformat()
        out.append({
            "title": e.get("title", "").strip(),
            "url": e["link"],
            "source": (e.get("source", {}) or {}).get("title") or "",
            "published": pub,
            "snippet": re.sub(r"<[^>]+>", " ", e.get("summary", "") or "")[:300],
        })
    return out


def collect() -> dict[str, list[dict]]:
    """Return {company: [article]} published within LOOKBACK_HOURS."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    today = date.today()
    found: dict[str, list[dict]] = {c: [] for c in COMPANIES}

    for company, queries in COMPANIES.items():
        for q in queries:
            found[company].extend(google_news_recent(q))
            time.sleep(0.25)

    window_start = today - timedelta(days=2)
    for extra in (fetch_industry_articles(window_start, today),
                  fetch_supplementary_articles(window_start, today)):
        for company, arts in extra.items():
            if company in found:
                found[company].extend(arts)

    result: dict[str, list[dict]] = {}
    for company, arts in found.items():
        seen_urls, seen_titles, keep = set(), set(), []
        for a in arts:
            title_key = _title_key(a["title"])
            if a["url"] in seen_urls or title_key in seen_titles:
                continue
            if not is_match(a, MATCH_PATTERNS.get(company, [])):
                continue
            pub = _parse_dt(a.get("published"))
            if pub and pub < cutoff:
                continue
            seen_urls.add(a["url"])
            seen_titles.add(title_key)
            keep.append(a)
        result[company] = keep
    return result


def _title_key(title: str) -> str:
    # Google News appends " - Source"; drop it so syndicated copies dedupe
    return re.sub(r"\s+-\s+[^-]+$", "", title).lower().strip()


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=IST)


def _hash(a: dict) -> str:
    return hashlib.sha1(_title_key(a["title"]).encode()).hexdigest()[:16]


def load_seen() -> dict[str, str]:
    if not SEEN_PATH.exists():
        return {}
    seen = json.loads(SEEN_PATH.read_text())
    cutoff = (date.today() - timedelta(days=SEEN_RETENTION_DAYS)).isoformat()
    return {h: d for h, d in seen.items() if d >= cutoff}


def score(articles: dict[str, list[dict]]) -> None:
    vader = SentimentIntensityAnalyzer()
    for arts in articles.values():
        for a in arts:
            c = vader.polarity_scores(f"{_title_key(a['title'])}. {a.get('snippet', '')}")["compound"]
            a["sentiment"] = "positive" if c >= 0.25 else "negative" if c <= -0.25 else "neutral"
            a["tier1"] = (a.get("source") or "").lower().strip() in TIER1


def mtd_sov() -> tuple[str, list[tuple[str, int, float]]]:
    """Latest month's share of voice from the dashboard dataset."""
    if not SOV_PATH.exists():
        return "", []
    d = json.loads(SOV_PATH.read_text())
    month = d["months"][-1]
    counts = [(c, len(d["data"][c].get(month["label"], []))) for c in d["companies"]]
    total = sum(n for _, n in counts) or 1
    return month["display"], sorted(((c, n, n / total * 100) for c, n in counts), key=lambda x: -x[1])


# ── email rendering ──────────────────────────────────────────────────────────

SENT_COLOR = {"positive": "#1a7f37", "neutral": "#6e7781", "negative": "#cf222e"}


def _article_row(a: dict) -> str:
    title = html.escape(re.sub(r"\s+-\s+[^-]+$", "", a["title"]))
    src = html.escape(a.get("source") or "")
    tier = ' <span style="font-size:11px;color:#9a6700;">★ Tier 1</span>' if a["tier1"] else ""
    sent = a["sentiment"]
    pub = _parse_dt(a.get("published"))
    when = pub.astimezone(IST).strftime("%d %b, %H:%M") if pub else ""
    return (
        '<tr><td style="padding:8px 0;border-bottom:1px solid #eee;">'
        f'<a href="{html.escape(a["url"])}" style="color:#1f2328;font-weight:600;text-decoration:none;">{title}</a><br>'
        f'<span style="font-size:12px;color:#6e7781;">{src}{" · " + when if when else ""}</span>{tier} '
        f'<span style="font-size:11px;color:{SENT_COLOR[sent]};">● {sent}</span>'
        "</td></tr>"
    )


def render(articles: dict[str, list[dict]], edition: str) -> tuple[str, str]:
    n_sun = len(articles.get("Sunsure", []))
    n_comp = sum(len(v) for k, v in articles.items() if k != "Sunsure")
    subject = f"Sunsure media digest ({edition}): {n_sun} Sunsure, {n_comp} competitor"

    parts = [
        '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:680px;color:#1f2328;">',
        f'<h2 style="margin:0 0 4px;color:{BRAND};">Sunsure media digest</h2>',
        f'<div style="font-size:13px;color:#6e7781;margin-bottom:16px;">{edition} edition · '
        f'{datetime.now(IST).strftime("%a %d %b %Y, %H:%M IST")}</div>',
    ]

    month, sov = mtd_sov()
    if sov:
        parts.append(f'<h3 style="margin:16px 0 6px;font-size:15px;">Share of voice, {month}</h3>'
                     '<table style="border-collapse:collapse;font-size:13px;">')
        for c, n, pct in sov:
            color = BRAND if c == "Sunsure" else "#8c959f"
            parts.append(
                f'<tr><td style="padding:2px 12px 2px 0;{"font-weight:600;" if c == "Sunsure" else ""}">{html.escape(c)}</td>'
                f'<td style="padding:2px 8px 2px 0;"><div style="background:{color};height:10px;width:{max(pct * 2.5, 2):.0f}px;"></div></td>'
                f'<td style="padding:2px 0;color:#6e7781;">{n} ({pct:.0f}%)</td></tr>'
            )
        parts.append("</table>")

    order = ["Sunsure"] + [c for c in articles if c != "Sunsure"]
    for company in order:
        arts = articles.get(company, [])
        if company != "Sunsure" and not arts:
            continue
        heading = "About Sunsure" if company == "Sunsure" else company
        parts.append(f'<h3 style="margin:20px 0 4px;font-size:15px;border-left:3px solid '
                     f'{BRAND if company == "Sunsure" else "#8c959f"};padding-left:8px;">'
                     f'{html.escape(heading)} <span style="color:#6e7781;font-weight:400;">({len(arts)})</span></h3>')
        if not arts:
            parts.append('<div style="font-size:13px;color:#6e7781;">No new coverage since the last digest.</div>')
            continue
        # Tier 1 outlets first, newest first within each group
        arts = sorted(arts, key=lambda a: a.get("published") or "", reverse=True)
        arts.sort(key=lambda a: not a["tier1"])
        parts.append('<table style="border-collapse:collapse;width:100%;">' + "".join(_article_row(a) for a in arts) + "</table>")

    if not n_sun and not n_comp:
        parts.append('<p style="font-size:13px;color:#6e7781;">Quiet window: no new coverage for any tracked company.</p>')
    footer = "Sentiment is automatic (VADER on headline + snippet) and can misread industry news."
    if DASHBOARD_URL:
        footer += f' <a href="{html.escape(DASHBOARD_URL)}">Open the dashboard</a>.'
    parts.append(f'<p style="font-size:11px;color:#8c959f;margin-top:24px;">{footer}</p></div>')
    return subject, "".join(parts)


def send(subject: str, body: str) -> None:
    user = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    to = [t.strip() for t in os.environ["DIGEST_TO"].split(",") if t.strip()]
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, ", ".join(to)
    msg.attach(MIMEText(body, "html", "utf-8"))
    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls()
        s.login(user, password)
        s.sendmail(user, to, msg.as_string())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    edition = "Morning" if datetime.now(IST).hour < 12 else "Evening"
    seen = load_seen()
    found = collect()
    new = {c: [a for a in arts if _hash(a) not in seen] for c, arts in found.items()}
    score(new)
    total = sum(len(v) for v in new.values())
    print(f"{total} new articles: " + ", ".join(f"{c} {len(v)}" for c, v in new.items()))

    subject, body = render(new, edition)
    if args.dry_run:
        out = ROOT / "digest_preview.html"
        out.write_text(body)
        print(f"Dry run: wrote {out.name}\nSubject: {subject}")
        return 0

    send(subject, body)
    today = date.today().isoformat()
    for arts in new.values():
        for a in arts:
            seen[_hash(a)] = today
    SEEN_PATH.write_text(json.dumps(seen, indent=0, sort_keys=True))
    print(f"Sent: {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
