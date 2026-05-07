#!/usr/bin/env python3
"""Brand monitor: fetch news via Google News RSS, classify with Claude, email a digest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import smtplib
import sqlite3
import sys
import urllib.parse
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

import feedparser
import yaml
from anthropic import Anthropic

ROOT = Path(__file__).parent
DB_PATH = ROOT / "seen.db"
CONFIG_PATH = ROOT / "config.yaml"

MODEL = "claude-haiku-4-5-20251001"

FILTER_PROMPT = """You are screening a news article for {company}.

About {company}: {company_desc}

Return ONLY a JSON object, no markdown fences, with these exact keys:
{{
  "is_about": true or false,           // is this article specifically about {company}?
  "is_competitor": true or false,      // is it about a named competitor of {company}?
  "relevance": "high" | "medium" | "low",
  "sentiment": "positive" | "neutral" | "negative",
  "category": "deal" | "award" | "leadership" | "financial" | "regulatory" | "technology" | "other",
  "summary": "one sentence describing the article",
  "why_it_matters": "one sentence on why {company} should care"
}}

Article:
Title: {title}
Source: {source}
Snippet: {snippet}
URL: {url}
"""


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen "
        "(url_hash TEXT PRIMARY KEY, url TEXT, first_seen TEXT)"
    )
    conn.commit()
    return conn


def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


def google_news_url(query: str, lang: str = "en-IN", geo: str = "IN") -> str:
    q = urllib.parse.quote(f'"{query}"')
    return (
        f"https://news.google.com/rss/search?q={q}"
        f"&hl={lang}&gl={geo}&ceid={geo}:{lang.split('-')[0]}"
    )


def fetch_all(cfg: dict):
    """Yield article dicts from every configured feed."""
    feeds: list[tuple[str, str]] = []
    for kw in cfg["keywords"]:
        feeds.append(("Google News", google_news_url(kw)))
    for kw in cfg.get("competitors", []):
        feeds.append(("Google News (competitor)", google_news_url(kw)))
    for extra in cfg.get("extra_feeds", []):
        feeds.append((extra.get("name", "RSS"), extra["url"]))

    for source_label, feed_url in feeds:
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"[warn] feed failed {source_label}: {e}", file=sys.stderr)
            continue
        for entry in parsed.entries:
            link = entry.get("link", "")
            if not link:
                continue
            yield {
                "title": entry.get("title", "").strip(),
                "url": link,
                "source": (entry.get("source", {}) or {}).get("title") or source_label,
                "published": entry.get("published", ""),
                "snippet": (entry.get("summary", "") or "")[:500],
            }


def classify(client: Anthropic, cfg: dict, article: dict) -> dict:
    prompt = FILTER_PROMPT.format(
        company=cfg["company"],
        company_desc=cfg["company_desc"],
        title=article["title"],
        source=article["source"],
        snippet=article["snippet"],
        url=article["url"],
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    return json.loads(text)


SENTIMENT_COLOR = {"positive": "#2E7D32", "negative": "#C62828", "neutral": "#616161"}


def render_group(articles: list[dict], heading: str) -> str:
    if not articles:
        return ""
    rows = []
    for a in articles:
        t = a["tag"]
        color = SENTIMENT_COLOR.get(t.get("sentiment"), "#616161")
        rows.append(
            f'<div style="margin:12px 0;padding:10px;border-left:3px solid {color};background:#fafafa">'
            f'<div><strong>{a["title"]}</strong> '
            f'<span style="color:#666">— {a["source"]}</span></div>'
            f'<div style="font-size:14px;color:#333;margin-top:4px">{t.get("summary","")}</div>'
            f'<div style="font-size:13px;color:#555"><em>Why it matters:</em> '
            f'{t.get("why_it_matters","")}</div>'
            f'<div style="font-size:12px;color:#888;margin-top:4px">'
            f'{t.get("category","")} · {t.get("relevance","")} · {t.get("sentiment","")} · '
            f'<a href="{a["url"]}">open article</a></div>'
            f'</div>'
        )
    return f"<h2 style='margin-top:24px'>{heading}</h2>" + "".join(rows)


def build_digest(articles: list[dict], company: str) -> str:
    rel_order = {"high": 0, "medium": 1, "low": 2}
    brand = [a for a in articles if a["tag"].get("is_about")]
    competitor = [
        a for a in articles
        if a["tag"].get("is_competitor") and not a["tag"].get("is_about")
    ]
    brand.sort(key=lambda a: rel_order.get(a["tag"].get("relevance"), 9))
    competitor.sort(key=lambda a: rel_order.get(a["tag"].get("relevance"), 9))

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f'<html><body style="font-family:-apple-system,Arial,sans-serif;'
        f'max-width:720px;margin:auto;padding:20px">'
        f'<h1 style="margin-bottom:0">{company} — brand monitor</h1>'
        f'<p style="color:#666;margin-top:4px">{stamp}</p>'
        + render_group(brand, f"About {company} ({len(brand)})")
        + render_group(competitor, f"Competitors ({len(competitor)})")
        + "</body></html>"
    )


def send_email(cfg: dict, subject: str, html: str) -> None:
    e = cfg["email"]
    msg = MIMEText(html, "html")
    msg["From"] = e["from"]
    msg["To"] = ", ".join(e["to"])
    msg["Subject"] = subject
    password = os.environ[e["smtp_password_env"]]
    with smtplib.SMTP(e["smtp_host"], e["smtp_port"]) as s:
        s.starttls()
        s.login(e["smtp_user"], password)
        s.send_message(msg)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print digest to stdout instead of emailing")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N classified articles (for testing)")
    args = ap.parse_args()

    cfg = load_config()
    db = init_db()
    client = Anthropic()  # reads ANTHROPIC_API_KEY

    keywords_lower = [k.lower() for k in cfg["keywords"] + cfg.get("competitors", [])]
    new_articles: list[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for a in fetch_all(cfg):
        h = url_hash(a["url"])
        if db.execute("SELECT 1 FROM seen WHERE url_hash = ?", (h,)).fetchone():
            continue

        text = f'{a["title"]} {a["snippet"]}'.lower()
        matches_keyword = any(kw in text for kw in keywords_lower)

        # always mark seen so we don't reprocess; only classify if keyword matches
        db.execute(
            "INSERT OR IGNORE INTO seen VALUES (?, ?, ?)",
            (h, a["url"], now_iso),
        )
        db.commit()

        if not matches_keyword:
            continue

        try:
            a["tag"] = classify(client, cfg, a)
        except Exception as e:
            print(f"[warn] classify failed for {a['url']}: {e}", file=sys.stderr)
            continue

        new_articles.append(a)
        if args.limit and len(new_articles) >= args.limit:
            break

    if not new_articles:
        print("No new articles.")
        return

    brand_hits = sum(1 for a in new_articles if a["tag"].get("is_about"))
    subject = f"{cfg['company']} brand monitor — {brand_hits} new mention(s)"
    html = build_digest(new_articles, cfg["company"])

    if args.dry_run:
        print(subject)
        print()
        print(html)
    else:
        send_email(cfg, subject, html)
        print(f"Sent: {subject}")


if __name__ == "__main__":
    main()
