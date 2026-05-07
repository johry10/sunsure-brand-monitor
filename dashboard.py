"""Sunsure Energy SOV Dashboard — local Streamlit app.
Run with: streamlit run dashboard.py"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).parent
DATA_PATH = ROOT / "sov_data.json"

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


data = load_data()
months = data["months"]
month_labels = [m["label"] for m in months]
month_display = {m["label"]: m["display"] for m in months}
all_companies = data["companies"]

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
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📈 SOV Trend",
    "📊 Monthly Composition",
    "📰 Highlights",
    "🗂️ Article Browser",
    "🏷️ Categories",
    "🎯 KRA Metrics",
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
            rows_a.append({
                "Date": (a["published"][:10] if a.get("published") else "—"),
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

- Google News RSS deprioritizes older content — coverage estimates for FY-early months may be undercounted
- Industry RSS feeds (Mercom, PV Tech, etc.) only return ~10-50 most recent items, so they can't backfill history
- Paywalled coverage (Bloomberg, FT, Mint Premium) is not included
- Social media, print, and broadcast monitoring not captured here
- Hexa Climate is a relatively new entrant — thin coverage is expected
- "Cleanmax" Feb–Mar 2026 spike is partly recent rebranded coverage; not a full FY trend
""")
