"""Sunsure Energy SOV Dashboard — local Streamlit app.
Run with: streamlit run dashboard.py"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Domain-specific lexicon tuning for renewable energy news.
# Stock VADER misses that "signs PPA" / "commissions plant" / "secures funding" are positive events.
RENEWABLE_LEXICON_BOOST = {
    "ppa": 1.5, "ppas": 1.5,
    "signs": 1.5, "signed": 1.5,
    "secures": 2.0, "secured": 2.0,
    "commissions": 2.5, "commissioned": 2.5, "commissioning": 2.0,
    "inaugurates": 2.0, "inaugurated": 2.0,
    "launches": 1.5, "launched": 1.5,
    "completes": 2.0, "completed": 2.0,
    "raises": 1.5, "raised": 1.5,
    "wins": 2.5, "won": 2.0,
    "awarded": 2.5,
    "expansion": 1.5, "expands": 1.5,
    "deal": 1.0,
    "partnership": 1.5,
    "milestone": 2.0,
    "record": 1.5,
    "operational": 1.5,
    "delays": -2.0, "delayed": -2.0,
    "fails": -2.5, "failed": -2.5,
    "cancels": -2.0, "cancelled": -2.0, "canceled": -2.0,
    "fines": -2.0, "fined": -2.0,
    "lawsuit": -2.5,
    "default": -2.0, "defaults": -2.0,
    "bankruptcy": -3.0,
    "drops": -1.5, "dropped": -1.5,
    "exits": -1.0, "exited": -1.0,
}

ROOT = Path(__file__).parent
# Prefer cleaned versions (noise-filtered). Fall back to raw if not present.
DATA_PATH = ROOT / "sov_data_clean.json" if (ROOT / "sov_data_clean.json").exists() else ROOT / "sov_data.json"
DATA_PATH_FY25 = ROOT / "sov_data_fy25_clean.json" if (ROOT / "sov_data_fy25_clean.json").exists() else ROOT / "sov_data_fy25.json"

# Sunsure brand color: RGB(253, 58, 32) → #FD3A20
SUNSURE_COLOR = "#FD3A20"
COMPANY_COLORS = {
    "Sunsure":         SUNSURE_COLOR,
    "ReNew":           "#1F77B4",
    "Cleanmax":        "#2CA02C",
    "Ampin":           "#FF7F0E",
    "Gentari/Amplus":  "#9467BD",
    "Hexa Climate":    "#8C564B",
    "Cleantech Solar": "#7F7F7F",
}

st.set_page_config(
    page_title="Sunsure Energy — SOV Dashboard",
    page_icon="☀️",
    layout="wide",
)


@st.cache_data
def load_data():
    return json.loads(DATA_PATH.read_text())


@st.cache_data
def load_fy25_data():
    if DATA_PATH_FY25.exists():
        return json.loads(DATA_PATH_FY25.read_text())
    return None


@st.cache_resource
def get_sentiment_analyzer():
    a = SentimentIntensityAnalyzer()
    a.lexicon.update(RENEWABLE_LEXICON_BOOST)
    return a


def sentiment_label(score: float) -> str:
    if score >= 0.05:
        return "positive"
    if score <= -0.05:
        return "negative"
    return "neutral"


@st.cache_data
def compute_sentiments(_data):
    """Score every article. Keyed by URL → {score, label}."""
    a = get_sentiment_analyzer()
    out = {}
    for company in _data["companies"]:
        for arts in _data["data"][company].values():
            for art in arts:
                text = art["title"] + " " + (art.get("snippet") or "")
                score = a.polarity_scores(text)["compound"]
                out[art["url"]] = {"score": score, "label": sentiment_label(score)}
    return out


def categorize(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["ppa", "power purchase", "signs", "supply agreement"]):
        return "Deal/PPA"
    if any(k in t for k in ["funding", "debt", "raise", "loan", "crore", "stake", "ipo"]):
        return "Financial"
    if any(k in t for k in ["commission", "operational", "starts", "online", "inaugurat"]):
        return "Project go-live"
    if any(k in t for k in ["acquir", "merger"]):
        return "M&A"
    if any(k in t for k in ["ceo", "appoint", "joins", "managing director"]):
        return "Leadership"
    if any(k in t for k in ["tender", "bid", "auction", "wins", "awarded"]):
        return "Tender/Bid"
    if any(k in t for k in ["manufactur", "factory", "plant", "facility", "module"]):
        return "Manufacturing"
    return "Other"


def is_industry_quote(article: dict) -> bool:
    """True if Sunsure appears to be quoted/cited as a source in the snippet."""
    text = ((article.get("snippet") or "") + " " + (article.get("title") or "")).lower()
    if re.search(r"sunsure.{0,40}(said|says|told|commented|noted|added|highlighted|stated)", text):
        return True
    if re.search(r"(said|says|told|according to|commented|per).{0,40}sunsure", text):
        return True
    return False


data = load_data()
data_fy25 = load_fy25_data()
sentiments = compute_sentiments(data)
months = data["months"]
month_labels = [m["label"] for m in months]
month_display = {m["label"]: m["display"] for m in months}
all_companies = data["companies"]


def sent_for(url: str) -> dict:
    return sentiments.get(url, {"score": 0.0, "label": "neutral"})


SENTIMENT_EMOJI = {"positive": "🟢", "neutral": "⚪", "negative": "🔴"}

# ─────────────── Sidebar ───────────────
with st.sidebar:
    st.markdown("### ⚙️ Filters")

    exclude_renew = st.toggle(
        "Exclude ReNew",
        value=False,
        help="ReNew has 5–8x the coverage of others. Exclude to see a fairer C&I-segment SOV.",
    )

    selected_companies = [c for c in all_companies if not (exclude_renew and c == "ReNew")]
    custom = st.multiselect(
        "Companies shown",
        options=all_companies,
        default=selected_companies,
    )
    selected_companies = custom if custom else selected_companies

    st.markdown("---")
    st.caption(f"Data refreshed: {data['generated_at'][:10]}")
    st.caption(f"Source: Google News RSS, India region")
    if st.button("🔄 Re-collect data", help="Run collect_data.py to refresh"):
        st.info("Open terminal, run: `python collect_data.py`, then refresh this page.")


# ─────────────── Build core dataframe ───────────────
rows = []
for m in month_labels:
    counts = {c: len(data["data"][c][m]) for c in selected_companies}
    total = sum(counts.values())
    for c in selected_companies:
        rows.append({
            "Month": m,
            "Display": month_display[m],
            "Company": c,
            "Articles": counts[c],
            "SOV %": round((counts[c] / total * 100), 1) if total else 0.0,
            "Total Pool": total,
        })
df = pd.DataFrame(rows)


# ─────────────── Header ───────────────
st.title("☀️ Sunsure Energy — Share of Voice Dashboard")
st.caption(
    f"FY 2025-26 (April 2025 – March 2026)"
    f"  ·  {sum(len(arts) for c in selected_companies for arts in data['data'][c].values())} articles tracked"
    f"  ·  {len(selected_companies)} companies"
)


# ─────────────── KPI cards ───────────────
def sunsure_kpis():
    s = df[df["Company"] == "Sunsure"].sort_values("Month")
    if s.empty:
        return None
    avg_sov = s["SOV %"].mean()
    best_by_sov = s.loc[s["SOV %"].idxmax()]
    best_by_count = s.loc[s["Articles"].idxmax()]
    latest = s.iloc[-1]
    earliest = s.iloc[0]
    delta = latest["SOV %"] - earliest["SOV %"]
    total_articles = int(s["Articles"].sum())

    latest_month = month_labels[-1]
    latest_df = df[df["Month"] == latest_month].sort_values("SOV %", ascending=False).reset_index(drop=True)
    rank = int(latest_df[latest_df["Company"] == "Sunsure"].index[0]) + 1

    return {
        "avg_sov": avg_sov,
        "best_by_sov": best_by_sov,
        "best_by_count": best_by_count,
        "latest_sov": latest["SOV %"],
        "delta": delta,
        "rank": rank,
        "total": len(selected_companies),
        "total_articles": total_articles,
    }


k = sunsure_kpis()
if k:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Sunsure avg SOV (FY26)", f"{k['avg_sov']:.1f}%")
    c2.metric(
        f"Latest ({month_display[month_labels[-1]]})",
        f"{k['latest_sov']:.1f}% SOV",
        f"{k['delta']:+.1f}pp vs Apr '25",
    )
    c3.metric(
        "🏆 Best by article count",
        f"{int(k['best_by_count']['Articles'])} articles",
        k['best_by_count']['Display'],
        delta_color="off",
    )
    c4.metric(
        "🏆 Best by SOV %",
        f"{k['best_by_sov']['SOV %']:.1f}%",
        k['best_by_sov']['Display'],
        delta_color="off",
    )
    c5.metric(f"Latest rank", f"#{k['rank']} of {k['total']}")

st.markdown("---")


# ─────────────── Tabs ───────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "📈 SOV Trend",
    "📊 Monthly Composition",
    "📰 Highlights",
    "🗂️ Article Browser",
    "🏷️ Categories",
    "🎯 KRA Metrics",
    "💚 Sentiment",
    "📅 FY25 vs FY26",
])

# ── Tab 1: SOV Trend (line)
with tab1:
    st.subheader("Monthly SOV Trend")
    pivot = df.pivot(index="Month", columns="Company", values="SOV %").reindex(month_labels)
    fig = go.Figure()
    for c in selected_companies:
        is_sunsure = c == "Sunsure"
        fig.add_trace(go.Scatter(
            x=[month_display[m] for m in month_labels],
            y=pivot[c].tolist(),
            mode="lines+markers",
            name=c,
            line=dict(width=4 if is_sunsure else 2, color=COMPANY_COLORS.get(c)),
            marker=dict(size=10 if is_sunsure else 6, color=COMPANY_COLORS.get(c)),
        ))
    fig.update_layout(
        height=500,
        yaxis_title="SOV (%)",
        xaxis_title=None,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, width="stretch")

    # Article count line below
    st.subheader("Article volume by month (absolute counts)")
    pivot_n = df.pivot(index="Month", columns="Company", values="Articles").reindex(month_labels)
    fig2 = go.Figure()
    for c in selected_companies:
        is_sunsure = c == "Sunsure"
        fig2.add_trace(go.Scatter(
            x=[month_display[m] for m in month_labels],
            y=pivot_n[c].tolist(),
            mode="lines+markers",
            name=c,
            line=dict(width=4 if is_sunsure else 2, color=COMPANY_COLORS.get(c)),
            marker=dict(color=COMPANY_COLORS.get(c)),
        ))
    fig2.update_layout(height=400, yaxis_title="Articles", hovermode="x unified")
    st.plotly_chart(fig2, width="stretch")


# ── Tab 2: Stacked bar
with tab2:
    st.subheader("SOV Composition by Month")
    fig = px.bar(df, x="Display", y="SOV %", color="Company",
                 color_discrete_map=COMPANY_COLORS,
                 category_orders={"Display": [month_display[m] for m in month_labels]})
    fig.update_layout(height=550, barmode="stack", xaxis_title=None)
    st.plotly_chart(fig, width="stretch")

    st.subheader("Article count composition by Month")
    fig2 = px.bar(df, x="Display", y="Articles", color="Company",
                  color_discrete_map=COMPANY_COLORS,
                  category_orders={"Display": [month_display[m] for m in month_labels]})
    fig2.update_layout(height=550, barmode="stack", xaxis_title=None)
    st.plotly_chart(fig2, width="stretch")


# ── Tab 3: Monthly highlights
with tab3:
    st.subheader("Monthly Highlights — Main Story per Company")
    st.caption("The 'main story' is identified by clustering similar headlines and picking the most-replicated cluster.")

    view_mode = st.radio("View mode", ["Single month", "All months — table"], horizontal=True)

    if view_mode == "Single month":
        sel_month = st.selectbox(
            "Select month",
            options=month_labels,
            format_func=lambda m: month_display[m],
            index=len(month_labels) - 1,
        )
        cols = st.columns(len(selected_companies))
        for i, c in enumerate(selected_companies):
            h = data["highlights"][c].get(sel_month)
            n = len(data["data"][c][sel_month])
            with cols[i]:
                st.markdown(f"### {c}")
                st.caption(f"{n} article{'s' if n != 1 else ''} this month")
                if h:
                    st.markdown(f"**📰 {h['title']}**")
                    src = h.get("source") or "—"
                    pub = h["published"][:10] if h.get("published") else "—"
                    st.caption(f"{src} · {pub}")
                    st.markdown(f"[Read article ↗]({h['url']})")
                else:
                    st.info("No coverage this month")
    else:
        # Build a wide table: rows = months, columns = companies, cells = title
        rows_table = []
        for m in month_labels:
            row = {"Month": month_display[m]}
            for c in selected_companies:
                h = data["highlights"][c].get(m)
                n = len(data["data"][c][m])
                if h:
                    title = h["title"][:80] + ("…" if len(h["title"]) > 80 else "")
                    row[c] = f"({n}) {title}"
                else:
                    row[c] = f"({n}) —"
            rows_table.append(row)
        df_table = pd.DataFrame(rows_table)
        st.dataframe(df_table, width="stretch", hide_index=True, height=460)


# ── Tab 4: Article browser
with tab4:
    st.subheader("Browse all articles")
    col1, col2 = st.columns(2)
    sel_company = col1.selectbox("Company", selected_companies, key="browser_company")
    sel_month = col2.selectbox(
        "Month", month_labels,
        format_func=lambda m: month_display[m],
        index=len(month_labels) - 1,
        key="browser_month",
    )

    articles = data["data"][sel_company][sel_month]
    st.caption(f"{len(articles)} article{'s' if len(articles) != 1 else ''}")

    if articles:
        rows_a = []
        for a in sorted(articles, key=lambda x: x.get("published") or "", reverse=True):
            s = sent_for(a["url"])
            rows_a.append({
                "Date": (a["published"][:10] if a.get("published") else "—"),
                "Sentiment": f"{SENTIMENT_EMOJI[s['label']]} {s['score']:+.2f}",
                "Source": a.get("source") or "—",
                "Title": a["title"],
                "Category": categorize(a["title"]),
                "URL": a["url"],
            })
        df_a = pd.DataFrame(rows_a)
        st.dataframe(
            df_a,
            width="stretch",
            hide_index=True,
            height=520,
            column_config={
                "URL": st.column_config.LinkColumn("Open"),
                "Title": st.column_config.TextColumn("Title", width="large"),
                "Sentiment": st.column_config.TextColumn("Sentiment", width="small"),
            },
        )
    else:
        st.info("No articles for this selection")


# ── Tab 5: Categories
with tab5:
    st.subheader("Sunsure: Coverage Category Mix Over Time")
    sunsure_rows = []
    for m in month_labels:
        cats = Counter(categorize(a["title"]) for a in data["data"]["Sunsure"][m])
        for cat, n in cats.items():
            sunsure_rows.append({"Month": month_display[m], "Category": cat, "Count": n})
    if sunsure_rows:
        df_cat = pd.DataFrame(sunsure_rows)
        fig = px.bar(df_cat, x="Month", y="Count", color="Category",
                     category_orders={"Month": [month_display[m] for m in month_labels]})
        fig.update_layout(height=500, barmode="stack")
        st.plotly_chart(fig, width="stretch")

    st.subheader("Sunsure's top sources (full FY)")
    src_counter = Counter()
    for m in month_labels:
        for a in data["data"]["Sunsure"][m]:
            if a.get("source"):
                src_counter[a["source"]] += 1
    if src_counter:
        df_src = pd.DataFrame(src_counter.most_common(20), columns=["Source", "Articles"])
        fig = px.bar(df_src, x="Articles", y="Source", orientation="h",
                     color_discrete_sequence=[SUNSURE_COLOR])
        fig.update_layout(height=500, yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, width="stretch")


# ── Tab 6: KRA Metrics
with tab6:
    st.subheader("FY26 Coverage Classification — for KRA Reporting")
    st.caption("Period: April 2025 – March 2026  ·  Heuristic classification, no LLM")

    kra_path = ROOT / "kra_classification.json"
    if not kra_path.exists():
        st.warning("`kra_classification.json` not found. Run `python classify_coverage.py` first.")
    else:
        kra = json.loads(kra_path.read_text())

        # Big numbers
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "📢 Press Releases",
            kra["press_releases"]["unique_count"],
            f"{kra['press_releases']['total_pickups']} total pickups",
            delta_color="off",
        )
        c2.metric("✍️ Authored Articles", kra["authored"]["count"], "May be undercounted", delta_color="off")
        c3.metric("📰 Media Features", kra["features"]["count"], delta_color="off")

        st.markdown(f"**Total articles in dataset**: {kra['total_articles']}")
        st.markdown("---")

        st.markdown("### 📢 Unique Press Releases (ranked by media pickup)")
        pr_rows = [
            {
                "Date": c["date"],
                "Pickups": c["pickups"],
                "Headline": c["representative_title"],
                "Outlets": ", ".join(c["outlets"][:5]) + ("…" if len(c["outlets"]) > 5 else ""),
            }
            for c in kra["press_releases"]["clusters"]
        ]
        df_pr = pd.DataFrame(pr_rows)
        st.dataframe(df_pr, width="stretch", hide_index=True, height=400)

        st.markdown("### 📰 Media Features")
        if kra["features"]["articles"]:
            feat_rows = [
                {"Date": a["date"], "Source": a["source"], "Title": a["title"], "URL": a["url"]}
                for a in kra["features"]["articles"]
            ]
            df_feat = pd.DataFrame(feat_rows)
            st.dataframe(
                df_feat,
                width="stretch",
                hide_index=True,
                height=400,
                column_config={"URL": st.column_config.LinkColumn("Open")},
            )

        if kra["authored"]["count"] == 0:
            st.warning(
                "**0 authored articles detected automatically** — likely an undercount. "
                "Google News snippets are too short to reliably catch bylines. "
                "Send a list of authored pieces you know exist (titles + months) to verify against the Media Features list."
            )

        st.info(
            "**Note on press release counts**: clusters include announcements *about* Sunsure where another company is the subject "
            "(e.g., 'Suzlon secures order from Sunsure'). For a stricter 'PR put out by Sunsure' count, filter to titles where "
            "Sunsure is the grammatical subject — typically ~50–55."
        )


# ── Tab 7: Sentiment
with tab7:
    st.subheader("💚 Sentiment Analysis (VADER + renewable-tuned lexicon)")
    st.caption(
        "Compound scores: -1 (very negative) to +1 (very positive). "
        "Threshold: ≥ +0.05 positive · ≤ -0.05 negative · else neutral. "
        "VADER lexicon boosted with industry terms (signs/secures/commissions/PPA = positive)."
    )

    # Build per-article sentiment dataframe
    sent_rows = []
    for c in selected_companies:
        for m in month_labels:
            for art in data["data"][c][m]:
                s = sent_for(art["url"])
                sent_rows.append({
                    "Company": c,
                    "Month": m,
                    "Display": month_display[m],
                    "Score": s["score"],
                    "Label": s["label"],
                })
    sent_df = pd.DataFrame(sent_rows)

    if sent_df.empty:
        st.warning("No articles in current selection.")
    else:
        # ── Avg sentiment trend per company
        st.markdown("##### Average sentiment by month")
        avg_by_month = sent_df.groupby(["Display", "Company"])["Score"].mean().reset_index()
        fig = go.Figure()
        for c in selected_companies:
            d = avg_by_month[avg_by_month["Company"] == c]
            d = d.set_index("Display").reindex([month_display[m] for m in month_labels]).reset_index()
            is_sunsure = c == "Sunsure"
            fig.add_trace(go.Scatter(
                x=d["Display"],
                y=d["Score"],
                mode="lines+markers",
                name=c,
                line=dict(width=4 if is_sunsure else 2, color=COMPANY_COLORS.get(c)),
                marker=dict(size=10 if is_sunsure else 6, color=COMPANY_COLORS.get(c)),
            ))
        fig.add_hline(y=0, line_dash="dash", line_color="gray", annotation_text="Neutral")
        fig.update_layout(
            height=480,
            yaxis_title="Avg compound sentiment",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, width="stretch")

        # ── Sunsure FY26 breakdown
        st.markdown("##### Sunsure FY26 — Sentiment Distribution")
        sunsure_sent = sent_df[sent_df["Company"] == "Sunsure"]
        if not sunsure_sent.empty:
            total = len(sunsure_sent)
            pos = (sunsure_sent["Label"] == "positive").sum()
            neu = (sunsure_sent["Label"] == "neutral").sum()
            neg = (sunsure_sent["Label"] == "negative").sum()
            avg = sunsure_sent["Score"].mean()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("🟢 Positive", f"{pos}", f"{pos/total*100:.0f}% of {total}", delta_color="off")
            c2.metric("⚪ Neutral", f"{neu}", f"{neu/total*100:.0f}% of {total}", delta_color="off")
            c3.metric("🔴 Negative", f"{neg}", f"{neg/total*100:.0f}% of {total}", delta_color="off")
            c4.metric("Avg score", f"{avg:+.3f}", "(higher is better)", delta_color="off")

        # ── Competitor comparison (avg sentiment FY)
        st.markdown("##### Average FY26 sentiment by company")
        avg_by_co = sent_df.groupby("Company")["Score"].agg(["mean", "count"]).reset_index()
        avg_by_co.columns = ["Company", "Avg score", "Articles"]
        avg_by_co = avg_by_co.sort_values("Avg score", ascending=False)
        fig_bar = px.bar(
            avg_by_co, x="Company", y="Avg score",
            color="Company", color_discrete_map=COMPANY_COLORS,
            text="Avg score",
        )
        fig_bar.update_traces(texttemplate="%{text:+.2f}", textposition="outside")
        fig_bar.update_layout(height=400, showlegend=False)
        st.plotly_chart(fig_bar, width="stretch")

        # ── Most positive / most negative for Sunsure
        st.markdown("##### 🟢 Most positive Sunsure articles (top 10)")
        sunsure_articles = []
        for m in month_labels:
            for art in data["data"]["Sunsure"][m]:
                sunsure_articles.append((art, sent_for(art["url"])["score"]))

        top_pos = sorted(sunsure_articles, key=lambda x: -x[1])[:10]
        for art, score in top_pos:
            d = (art.get("published") or "")[:10]
            src = art.get("source") or "—"
            st.markdown(f"`{score:+.2f}` · `{d}` · **[{src}]** [{art['title']}]({art['url']})")

        st.markdown("##### 🔴 Most negative Sunsure articles (top 10)")
        top_neg = sorted(sunsure_articles, key=lambda x: x[1])[:10]
        if not top_neg or top_neg[0][1] >= 0:
            st.success("No negative-scoring Sunsure articles found in FY26 — your coverage is uniformly positive or neutral.")
        else:
            for art, score in top_neg:
                if score >= 0:
                    break
                d = (art.get("published") or "")[:10]
                src = art.get("source") or "—"
                st.markdown(f"`{score:+.2f}` · `{d}` · **[{src}]** [{art['title']}]({art['url']})")

    with st.expander("ℹ️ How this works + caveats"):
        st.markdown("""
**Methodology**

- **VADER** (Valence Aware Dictionary and sEntiment Reasoner) — rules-based lexicon with ~7,500 words scored for sentiment, plus heuristics for negation/intensifiers.
- **Custom boost**: VADER doesn't know that "signs PPA" or "commissions plant" are positive in renewable-energy context. The lexicon has been augmented with ~30 domain terms (signs, secures, commissions, PPA, awarded, milestone, etc.).
- **Score**: compound score from -1 to +1 across the title + snippet.
- **Label**: positive ≥ +0.05 · neutral · negative ≤ -0.05.

**Caveats**

- Lexicon-based sentiment is ~75-80% accurate on news headlines vs human raters
- Misses sarcasm, complex negation ("not bad" → still positive), and ironic framing
- Snippets from Google News are short (~200 chars), so longer-context cues are missed
- A piece can score "negative" because of negative *industry* news while being neutral *for Sunsure* (e.g., "Industry concerned about new tax — Sunsure CEO comments")
- For nuanced / strategic sentiment, an LLM would do better — but VADER is free, fast, and offline.
""")


# ── Tab 8: FY25 vs FY26 Comparison
with tab8:
    st.subheader("FY25 vs FY26 — Year-on-Year Comparison")
    st.caption("FY25 = Apr 2024 – Mar 2025  ·  FY26 = Apr 2025 – Mar 2026")

    if data_fy25 is None:
        st.error("`sov_data_fy25.json` not found. Run `python collect_data_fy25.py` first.")
    else:
        fy25_months = [m["label"] for m in data_fy25["months"]]
        fy26_months = month_labels  # already loaded

        # ── Helper: compute SOV summary for a given dataset
        def fy_sov_summary(d: dict, months: list[str], companies: list[str]) -> dict:
            """Returns {company: {total_articles, avg_sov, monthly_sov[]}} for all companies."""
            result = {}
            for c in companies:
                monthly_counts = [len(d["data"][c].get(m, [])) for m in months]
                monthly_totals = [
                    sum(len(d["data"][cc].get(m, [])) for cc in companies)
                    for m in months
                ]
                monthly_sov = [
                    round(cnt / tot * 100, 1) if tot else 0.0
                    for cnt, tot in zip(monthly_counts, monthly_totals)
                ]
                total_pool = sum(monthly_totals)
                total_articles = sum(monthly_counts)
                avg_sov = round(total_articles / total_pool * 100, 1) if total_pool else 0.0
                result[c] = {
                    "total_articles": total_articles,
                    "avg_sov": avg_sov,
                    "monthly_sov": monthly_sov,
                    "monthly_counts": monthly_counts,
                }
            return result

        fy25_summary = fy_sov_summary(data_fy25, fy25_months, all_companies)
        fy26_summary = fy_sov_summary(data, fy26_months, all_companies)

        # ── 1. KPI cards for Sunsure
        st.markdown("### 1. Overall SOV — Sunsure Energy")
        s25 = fy25_summary["Sunsure"]
        s26 = fy26_summary["Sunsure"]
        delta_sov = round(s26["avg_sov"] - s25["avg_sov"], 1)
        delta_articles = s26["total_articles"] - s25["total_articles"]

        kc1, kc2, kc3, kc4 = st.columns(4)
        kc1.metric("FY25 avg SOV", f"{s25['avg_sov']:.1f}%",
                   f"{s25['total_articles']} articles", delta_color="off")
        kc2.metric("FY26 avg SOV", f"{s26['avg_sov']:.1f}%",
                   f"{s26['total_articles']} articles", delta_color="off")
        kc3.metric("SOV change (pp)", f"{delta_sov:+.1f}pp",
                   "FY25 → FY26", delta_color="normal")
        kc4.metric("Article volume change", f"{delta_articles:+d}",
                   "FY25 → FY26", delta_color="normal")

        # ── SOV comparison bar chart (all companies, FY25 vs FY26)
        st.markdown("##### FY25 vs FY26 SOV — all companies")
        compare_rows = []
        for c in all_companies:
            compare_rows.append({"Company": c, "FY": "FY25", "SOV %": fy25_summary[c]["avg_sov"],
                                  "Articles": fy25_summary[c]["total_articles"]})
            compare_rows.append({"Company": c, "FY": "FY26", "SOV %": fy26_summary[c]["avg_sov"],
                                  "Articles": fy26_summary[c]["total_articles"]})
        df_compare = pd.DataFrame(compare_rows)

        fig_sov = px.bar(
            df_compare, x="Company", y="SOV %", color="FY",
            barmode="group",
            color_discrete_map={"FY25": "#AAAAAA", "FY26": SUNSURE_COLOR},
            text="SOV %",
        )
        fig_sov.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig_sov.update_layout(height=430, yaxis_title="Avg SOV (%)", xaxis_title=None,
                               legend_title=None)
        st.plotly_chart(fig_sov, width="stretch")

        # Sunsure SOV trend comparison (FY25 line vs FY26 line on same chart)
        st.markdown("##### Sunsure: monthly SOV trajectory — FY25 vs FY26")
        fy25_disp = [data_fy25["months"][i]["display"] for i in range(12)]
        fy26_disp = [month_display[m] for m in fy26_months]
        month_labels_short = ["Apr", "May", "Jun", "Jul", "Aug", "Sep",
                               "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(
            x=month_labels_short,
            y=s25["monthly_sov"],
            mode="lines+markers",
            name="FY25",
            line=dict(width=2, color="#AAAAAA", dash="dash"),
            marker=dict(size=7),
            customdata=fy25_disp,
            hovertemplate="%{customdata}: %{y:.1f}%<extra>FY25</extra>",
        ))
        fig_trend.add_trace(go.Scatter(
            x=month_labels_short,
            y=s26["monthly_sov"],
            mode="lines+markers",
            name="FY26",
            line=dict(width=3, color=SUNSURE_COLOR),
            marker=dict(size=9, color=SUNSURE_COLOR),
            customdata=fy26_disp,
            hovertemplate="%{customdata}: %{y:.1f}%<extra>FY26</extra>",
        ))
        fig_trend.update_layout(
            height=400,
            yaxis_title="Sunsure SOV (%)",
            xaxis_title="Month (Apr → Mar)",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_trend, width="stretch")

        # Summary table
        with st.expander("Full SOV table — FY25 vs FY26 (all companies)"):
            tbl_rows = []
            for c in all_companies:
                s25c = fy25_summary[c]
                s26c = fy26_summary[c]
                tbl_rows.append({
                    "Company": c,
                    "FY25 Articles": s25c["total_articles"],
                    "FY25 SOV %": f"{s25c['avg_sov']:.1f}%",
                    "FY26 Articles": s26c["total_articles"],
                    "FY26 SOV %": f"{s26c['avg_sov']:.1f}%",
                    "SOV Δ (pp)": f"{s26c['avg_sov'] - s25c['avg_sov']:+.1f}",
                    "Volume Δ": f"{s26c['total_articles'] - s25c['total_articles']:+d}",
                })
            st.dataframe(pd.DataFrame(tbl_rows), hide_index=True, width="stretch")

        st.markdown("---")

        # ── 2. Industry stories quoting/tagging Sunsure
        st.markdown("### 2. Industry Stories Tagging Sunsure as a Source")
        st.caption(
            "Detected by scanning snippets for patterns like "
            '"Sunsure said / told / commented / according to Sunsure". '
            "Benchmark: ~2 per month."
        )

        def count_quotes(d: dict, months: list[str]) -> list[int]:
            return [
                sum(1 for a in d["data"]["Sunsure"].get(m, []) if is_industry_quote(a))
                for m in months
            ]

        fy25_quotes = count_quotes(data_fy25, fy25_months)
        fy26_quotes = count_quotes(data, fy26_months)
        total_fy25_quotes = sum(fy25_quotes)
        total_fy26_quotes = sum(fy26_quotes)
        avg_fy25_q = total_fy25_quotes / 12
        avg_fy26_q = total_fy26_quotes / 12

        qc1, qc2, qc3 = st.columns(3)
        qc1.metric("FY25 quote detections", total_fy25_quotes,
                   f"{avg_fy25_q:.1f}/month avg", delta_color="off")
        qc2.metric("FY26 quote detections", total_fy26_quotes,
                   f"{avg_fy26_q:.1f}/month avg", delta_color="off")
        qc3.metric("Change", f"{total_fy26_quotes - total_fy25_quotes:+d}",
                   "FY25 → FY26", delta_color="normal")

        fig_q = go.Figure()
        fig_q.add_trace(go.Bar(
            x=month_labels_short, y=fy25_quotes, name="FY25",
            marker_color="#AAAAAA",
        ))
        fig_q.add_trace(go.Bar(
            x=month_labels_short, y=fy26_quotes, name="FY26",
            marker_color=SUNSURE_COLOR,
        ))
        fig_q.add_hline(y=2, line_dash="dot", line_color="#555555",
                        annotation_text="2/month target", annotation_position="top left")
        fig_q.update_layout(
            height=380,
            barmode="group",
            yaxis_title="Articles with Sunsure as source",
            xaxis_title="Month (Apr → Mar)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_q, width="stretch")

        with st.expander("ℹ️ Methodology note on quote detection"):
            st.markdown("""
**How quotes are detected**: The scanner looks for proximity patterns in the 300-character snippet:
- *"Sunsure said / told / commented / noted / highlighted"* — company cited after a verb
- *"said / told / according to ... Sunsure"* — company cited before the verb phrase

**Caveats**: Google News snippets are short (~200–300 chars). Many quotes will be missed because
the relevant text appears beyond the snippet. Treat this as a **lower bound**. The actual number
of articles where Sunsure is quoted will be higher. Manual review of the Media Features list
(KRA Metrics tab) will give the definitive count.
""")

        st.markdown("---")

        # ── 3. Website traffic
        st.markdown("### 3. Website Traffic — FY25 vs FY26")
        st.info(
            "**Website traffic data is not available via RSS or Google News.** "
            "This requires Google Analytics (GA4) or a SimilarWeb export. "
            "Enter your monthly session data below to generate the comparison chart.",
            icon="ℹ️",
        )

        with st.expander("Enter website traffic data (optional)", expanded=False):
            st.caption("Paste monthly sessions from Google Analytics → Reports → Traffic → Sessions. "
                       "Leave blank if unavailable.")
            col_fy25, col_fy26 = st.columns(2)

            with col_fy25:
                st.markdown("**FY25 — monthly sessions**")
                traffic_fy25 = {}
                for short, label in zip(month_labels_short, fy25_disp):
                    v = st.number_input(label, min_value=0, value=0,
                                        key=f"t25_{short}", step=100)
                    traffic_fy25[short] = v

            with col_fy26:
                st.markdown("**FY26 — monthly sessions**")
                traffic_fy26 = {}
                for short, label in zip(month_labels_short, fy26_disp):
                    v = st.number_input(label, min_value=0, value=0,
                                        key=f"t26_{short}", step=100)
                    traffic_fy26[short] = v

        t25_vals = [traffic_fy25.get(s, 0) for s in month_labels_short]
        t26_vals = [traffic_fy26.get(s, 0) for s in month_labels_short]
        has_traffic = any(v > 0 for v in t25_vals + t26_vals)

        if has_traffic:
            total_t25 = sum(t25_vals)
            total_t26 = sum(t26_vals)
            delta_t = ((total_t26 - total_t25) / total_t25 * 100) if total_t25 else 0

            tc1, tc2, tc3 = st.columns(3)
            tc1.metric("FY25 total sessions", f"{total_t25:,}")
            tc2.metric("FY26 total sessions", f"{total_t26:,}")
            tc3.metric("YoY change", f"{delta_t:+.1f}%", delta_color="normal")

            fig_t = go.Figure()
            fig_t.add_trace(go.Bar(
                x=month_labels_short, y=t25_vals, name="FY25",
                marker_color="#AAAAAA",
            ))
            fig_t.add_trace(go.Bar(
                x=month_labels_short, y=t26_vals, name="FY26",
                marker_color=SUNSURE_COLOR,
            ))
            fig_t.update_layout(
                height=380, barmode="group",
                yaxis_title="Monthly sessions",
                xaxis_title="Month (Apr → Mar)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig_t, width="stretch")
        else:
            st.caption("Charts will appear once you enter traffic data above.")


# ─────────────── Footer ───────────────
st.markdown("---")
with st.expander("ℹ️ Methodology & caveats"):
    st.markdown("""
**Methodology**

- **Data source**: Google News RSS, India region (`hl=en-IN&gl=IN&ceid=IN:en`)
- **Date filtering**: per-month queries using `after:` and `before:` operators
- **Search variants**: each company queried with multiple name variants (e.g., Gentari + Amplus Solar + Amplus Energy to catch the rebrand)
- **Highlights**: titles clustered by first 6 words; biggest cluster represents the "main story"; longest title in that cluster is shown
- **Categories**: keyword-based classification of headlines (Deal/PPA, Financial, Project go-live, etc.)

**Caveats**

- **Noise filter applied**: articles are kept only if the company's name appears in the title or snippet. Raw Google News RSS returns loosely related articles (e.g., "KSL Cleantech" triggering for "Cleantech Solar") — the filter removes these. Noise rates ranged from 16% (Cleanmax) to 91% (Hexa Climate) in raw data.
- Google News RSS deprioritizes older content — coverage estimates for FY-early months may be undercounted
- Industry RSS feeds (Mercom, PV Tech, etc.) only return ~10-50 most recent items, so they can't backfill history
- Paywalled coverage (Bloomberg, FT, Mint Premium) is not included
- Social media, print, and broadcast monitoring not captured here
- Hexa Climate is a relatively new entrant — thin coverage is expected
- "Cleanmax" Feb–Mar 2026 spike is partly recent rebranded coverage; not a full FY trend
""")
