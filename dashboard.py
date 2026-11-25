# ============================================================
# DASHBOARD.PY — Market Master Scanner + Hot Themes + Theme Search
# Requires: streamlit>=1.40 for st.pills (fallback included)
# ============================================================

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
import requests
import io
import ta
import time
import math
import difflib
from datetime import datetime

st.set_page_config(page_title="Market Master Scanner", layout="wide")
st.title("📈 Ultimate Market & Sector Scanner")

PERIODS = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252, "3Y": 756, "5Y": 1260}

METALS = {
    "Gold": "GC=F",
    "Silver": "SI=F",
    "Copper": "HG=F",
    "Platinum": "PL=F",
    "Palladium": "PA=F"
}

# ============================================================
# THEME REGISTRY
# ============================================================
THEMES = {
    "Defence": {
        "aliases": ["defense", "arms", "military", "aerospace", "hal", "bel"],
        "last_reviewed": "2026-11-25",
        "verified": False,
        "global_universe": [
            {"name": "Lockheed Martin", "ticker": "LMT", "country": "US", "flag": "🇺🇸",
             "market_cap_usd_bn": 115, "thesis": "F-35, missiles, space"},
            {"name": "RTX", "ticker": "RTX", "country": "US", "flag": "🇺🇸",
             "market_cap_usd_bn": 165, "thesis": "Patriot, missiles, aerospace"},
            {"name": "Northrop Grumman", "ticker": "NOC", "country": "US", "flag": "🇺🇸",
             "market_cap_usd_bn": 72, "thesis": "B-21, space, nuclear"},
            {"name": "BAE Systems", "ticker": "BA.L", "country": "UK", "flag": "🇬🇧",
             "market_cap_usd_bn": 55, "thesis": "Eurofighter, submarines"},
            {"name": "Rheinmetall", "ticker": "RHM.DE", "country": "DE", "flag": "🇩🇪",
             "market_cap_usd_bn": 28, "thesis": "Ammo, armor (Europe rearm)"},
            {"name": "Hindustan Aeronautics", "ticker": "HAL.NS", "country": "IN", "flag": "🇮🇳",
             "market_cap_usd_bn": 38, "thesis": "Tejas, helicopters, engines"},
        ],
        "india_direct": [
            {"name": "HAL", "ticker": "HAL.NS", "link": "Aircraft mfg",
             "reason": "Tejas Mk1A, LCH, engines; order book >₹1.2 L Cr"},
            {"name": "Bharat Electronics", "ticker": "BEL.NS", "link": "Defence electronics",
             "reason": "Radars, EW, missiles; top MoD electronics share"},
            {"name": "Bharat Dynamics", "ticker": "BDL.NS", "link": "Missiles/torpedoes",
             "reason": "Akash, Astra, Konkurs; stockpile replenishment"},
            {"name": "Mazagon Dock", "ticker": "MAZDOCK.NS", "link": "Submarines/warships",
             "reason": "Scorpene subs, destroyers; naval capex"},
            {"name": "Solar Industries", "ticker": "SOLARINDS.NS", "link": "Ammo/explosives",
             "reason": "Largest Indian explosives maker; defence exports"},
        ],
        "india_indirect": [
            {"name": "Data Patterns", "ticker": "DATAPATTNS.NS", "link_type": "Avionics",
             "reason": "Radar/EW subsystems for HAL/BEL"},
            {"name": "Apollo Micro Systems", "ticker": "APOLLO.NS", "link_type": "Embedded systems",
             "reason": "Missile electronics, naval systems"},
            {"name": "Astra Microwave", "ticker": "ASTRAMICRO.NS", "link_type": "RF/microwave",
             "reason": "Radar seekers, satellite comms"},
            {"name": "MTAR Technologies", "ticker": "MTARTECH.NS", "link_type": "Precision eng",
             "reason": "Nuclear + defense precision components"},
        ],
        "policy_kpis": [
            {"label": "FY27 defence capex (proposed)", "value": "₹2.19 L Cr", "as_of": "Nov 2026"},
            {"label": "FY26 defence exports", "value": "₹38,424 Cr", "as_of": "FY26"},
            {"label": "Export target by 2029", "value": "₹50,000 Cr", "as_of": "Policy"},
            {"label": "Positive Indigenisation items", "value": "5,417", "as_of": "Aug 2026"},
        ],
        "policy_timeline": [
            {"year": 2020, "event": "Defence PLI; FDI 74% automatic"},
            {"year": 2021, "event": "First Positive Indigenisation List (101 items)"},
            {"year": 2023, "event": "Fourth PIL; defence exports cross ₹15,000 Cr"},
            {"year": 2025, "event": "Exports ₹23,000+ Cr; 5th/6th PILs notified"},
            {"year": 2026, "event": "FY27 capex proposed ₹2.19 L Cr; exports ₹38,424 Cr"},
        ],
        "risks": [
            {"risk": "Tejas/engine supply delays", "likelihood": 3, "impact": 5, "category": "Execution"},
            {"risk": "Budget reallocation away", "likelihood": 2, "impact": 4, "category": "Policy"},
            {"risk": "Export approval bottlenecks", "likelihood": 3, "impact": 3, "category": "Regulatory"},
            {"risk": "Private competition erodes PSU share", "likelihood": 3, "impact": 3, "category": "Competition"},
            {"risk": "Geopolitical de-escalation", "likelihood": 2, "impact": 4, "category": "Macro"},
        ],
        "watchlist": [
            {"metric": "MoD capital outlay (FY27)", "current": "₹2.19 L Cr", "threshold": "<₹2.0 L Cr", "source": "MoD", "frequency": "Annual"},
            {"metric": "Defence exports", "current": "₹38,424 Cr", "threshold": "<₹30,000 Cr", "source": "MoD", "frequency": "Annual"},
            {"metric": "HAL order book", "current": ">₹1.2 L Cr", "threshold": "<₹1.0 L Cr", "source": "Company", "frequency": "Quarterly"},
            {"metric": "BEL order inflow", "current": "~₹25,000 Cr/yr", "threshold": "<₹20,000 Cr", "source": "Company", "frequency": "Quarterly"},
        ],
        "source_urls": [
            "https://www.angelone.in/news/Economy/hal-bel-and-other-defence-stocks-in-focus-as-defence-ministry-seeks-20-capex-hike-for-fy27",
            "https://www.ibef.org/industry/defence-manufacturing",
        ],
    },
    # Add "Semiconductors", "Green Hydrogen", "Pharma", etc. using the same schema.
}

# ============================================================
# CURRENCY / FX HELPERS
# ============================================================
# Suffix → FX pair. Pairs in "XXX=X" format mean USD/XXX (1 USD = X XXX).
# Pairs in "XXXUSD=X" format mean XXX/USD (1 XXX = Y USD).
SUFFIX_TO_PAIR = {
    ".NS": "INR=X", ".BO": "INR=X",
    ".L":  "GBPUSD=X",
    ".DE": "EURUSD=X", ".PA": "EURUSD=X", ".AS": "EURUSD=X",
    ".SW": "CHFUSD=X",
    ".T":  "JPY=X",
    ".KS": "KRW=X",
    ".TW": "TWD=X",
    ".HK": "HKD=X",
}


@st.cache_data(ttl=3600)
def get_fx_rate(pair):
    """Fetch latest FX rate for a pair."""
    try:
        d = yf.download(pair, period="5d", interval="1d",
                        progress=False, auto_adjust=True)
        if d.empty:
            return None
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        return float(d["Close"].dropna().iloc[-1])
    except Exception:
        return None


@st.cache_data(ttl=3600)
def get_market_cap_usd(ticker):
    """Get market cap in USD, converting from local currency via FX rate."""
    try:
        fi = yf.Ticker(ticker).fast_info
    except Exception:
        return None

    mc = None
    for key in ("market_cap", "marketCap"):
        try:
            v = fi[key]
            if v:
                mc = float(v)
                break
        except Exception:
            pass
        try:
            v = getattr(fi, key, None)
            if v:
                mc = float(v)
                break
        except Exception:
            pass
    if not mc:
        return None

    pair = None
    for suffix, p in SUFFIX_TO_PAIR.items():
        if ticker.endswith(suffix):
            pair = p
            break
    if not pair:
        return mc  # assume USD

    rate = get_fx_rate(pair)
    if not rate or rate <= 0:
        return mc  # fallback to local value

    if "USD" in pair:
        # XXXUSD=X → 1 XXX = rate USD
        return mc * rate
    else:
        # XXX=X → 1 USD = rate XXX → divide
        return mc / rate


def days_since_review(last_reviewed_str):
    try:
        dt = datetime.strptime(last_reviewed_str, "%Y-%m-%d")
        return (datetime.now() - dt).days
    except Exception:
        return None


# ============================================================
# THEME DATA HELPERS
# ============================================================
@st.cache_data(ttl=3600)
def batch_prices(tickers_tuple, period="1y"):
    """Single batched yf.download; returns dict {ticker: DataFrame}."""
    tickers = list(tickers_tuple)
    if not tickers:
        return {}
    try:
        data = yf.download(
            tickers, period=period, interval="1d",
            group_by="ticker", progress=False, threads=True, auto_adjust=True
        )
    except Exception:
        return {}
    if data.empty:
        return {}

    out = {}
    if isinstance(data.columns, pd.MultiIndex):
        for t in tickers:
            try:
                if t in data.columns.get_level_values(0):
                    d = data[t].dropna()
                    if not d.empty:
                        out[t] = d
            except Exception:
                continue
    else:
        if len(tickers) == 1:
            d = data.dropna()
            if not d.empty:
                out[tickers[0]] = d
    return out


def compute_rsi(close):
    try:
        return ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]
    except Exception:
        return np.nan


def compute_momentum(closes, days):
    if len(closes) <= days:
        return np.nan
    old = closes.iloc[-(days + 1)]
    cur = closes.iloc[-1]
    if pd.isna(old) or old == 0:
        return np.nan
    return (cur / old - 1) * 100


# ============================================================
# THEME RENDERERS
# ============================================================
def render_scorecard(theme):
    all_tickers = (
        [x["ticker"] for x in theme["global_universe"]]
        + [x["ticker"] for x in theme["india_direct"]]
        + [x["ticker"] for x in theme["india_indirect"]]
    )
    prices = batch_prices(tuple(all_tickers), period="1y")
    if not prices:
        st.warning("No price data available for scorecard.")
        return

    rets_3m = [compute_momentum(df["Close"], 63) for df in prices.values() if len(df) > 63]
    rets_3m = [r for r in rets_3m if pd.notna(r)]
    momentum = float(np.mean(rets_3m)) if rets_3m else 0.0

    above_200, valid_200 = 0, 0
    for df in prices.values():
        if len(df) >= 200:
            valid_200 += 1
            ma200 = df["Close"].rolling(200).mean().iloc[-1]
            if pd.notna(ma200) and df["Close"].iloc[-1] > ma200:
                above_200 += 1
    breadth = (above_200 / valid_200 * 100) if valid_200 else 0.0

    positions = []
    for df in prices.values():
        if len(df) > 252:
            high = df["Close"].tail(252).max()
            low = df["Close"].tail(252).min()
            cur = df["Close"].iloc[-1]
            if pd.notna(high) and pd.notna(low) and high > low:
                positions.append((cur - low) / (high - low) * 100)
    val_pct = float(np.mean(positions)) if positions else 0.0

    # India exposure in USD
    india_caps, global_caps = [], []
    for item in theme["india_direct"] + theme["india_indirect"]:
        mc = get_market_cap_usd(item["ticker"])
        if mc:
            india_caps.append(mc)
    for item in theme["global_universe"]:
        mc = get_market_cap_usd(item["ticker"])
        if not mc:
            mc = item.get("market_cap_usd_bn", 0) * 1e9 or None
        if mc:
            if item["flag"] == "🇮🇳":
                india_caps.append(mc)
            else:
                global_caps.append(mc)
    total_cap = sum(india_caps) + sum(global_caps)
    india_exposure = (sum(india_caps) / total_cap * 100) if total_cap else 0.0

    vols = []
    for df in prices.values():
        if len(df) > 30:
            r = df["Close"].pct_change().dropna()
            if len(r) > 0:
                vols.append(float(r.std() * np.sqrt(252)))
    ann_vol = float(np.mean(vols)) if vols else 0.0
    risk_label = "Low" if ann_vol < 0.20 else ("Medium" if ann_vol < 0.35 else "High")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Momentum (3M avg)", f"{momentum:+.1f}%")
    c2.metric("Breadth (>200DMA)", f"{breadth:.0f}%")
    c3.metric("Range position (1Y)", f"{val_pct:.0f}%")
    c4.metric("India exposure", f"{india_exposure:.0f}%")
    c5.metric("Risk (vol)", f"{ann_vol*100:.0f}% / {risk_label}")

    # Staleness check
    days = days_since_review(theme.get("last_reviewed", ""))
    if days is not None and days > 90:
        st.warning(
            f"⚠️ **Theme data is {days} days old** (last reviewed "
            f"{theme.get('last_reviewed')}). Policy KPIs, risks, and rationale "
            f"may be stale — verify against source URLs before acting."
        )

    st.caption(
        f"Last reviewed: {theme.get('last_reviewed','—')} | "
        f"Verified: {'✅' if theme.get('verified') else '⚠️ Not verified'} | "
        f"Valuation proxy = avg position within 1Y price range (0%=lows, 100%=highs)"
    )


def render_treemap(theme):
    all_tickers = (
        [item["ticker"] for item in theme["global_universe"]]
        + [item["ticker"] for item in theme["india_direct"]]
        + [item["ticker"] for item in theme["india_indirect"]]
    )
    prices = batch_prices(tuple(all_tickers), period="2y")

    def get_ret(item):
        df = prices.get(item["ticker"])
        return compute_momentum(df["Close"], 252) if df is not None and len(df) > 252 else np.nan

    rows = []
    for item in theme["global_universe"]:
        mc_bn = item.get("market_cap_usd_bn", 0)
        if not mc_bn:
            mc_local = get_market_cap_usd(item["ticker"])
            mc_bn = (mc_local / 1e9) if mc_local else 1
        ret = get_ret(item)
        rows.append({
            "Region": "🌍 Global",
            "Country": item["flag"] + " " + item["country"],
            "Name": item["name"],
            "Ticker": item["ticker"],
            "Market Cap ($B)": mc_bn,
            "1Y Return (%)": ret if pd.notna(ret) else 0.0,
        })
    for item in theme["india_direct"]:
        mc_local = get_market_cap_usd(item["ticker"])
        ret = get_ret(item)
        rows.append({
            "Region": "🇮🇳 India Direct",
            "Country": "🇮🇳 IN",
            "Name": item["name"],
            "Ticker": item["ticker"],
            "Market Cap ($B)": (mc_local / 1e9) if mc_local else 0.5,
            "1Y Return (%)": ret if pd.notna(ret) else 0.0,
        })
    for item in theme["india_indirect"]:
        mc_local = get_market_cap_usd(item["ticker"])
        ret = get_ret(item)
        rows.append({
            "Region": "🇮🇳 India Indirect",
            "Country": "🇮🇳 IN",
            "Name": item["name"],
            "Ticker": item["ticker"],
            "Market Cap ($B)": (mc_local / 1e9) if mc_local else 0.2,
            "1Y Return (%)": ret if pd.notna(ret) else 0.0,
        })

    df = pd.DataFrame(rows)
    df = df[df["Market Cap ($B)"] > 0]
    if df.empty:
        st.info("No market cap data available for treemap.")
        return

    fig = px.treemap(
        df, path=["Region", "Country", "Name"], values="Market Cap ($B)",
        color="1Y Return (%)", color_continuous_scale="RdYlGn",
        color_continuous_midpoint=0,
        title="Theme Universe — size = market cap ($B), color = 1Y return (%)"
    )
    fig.update_layout(template="plotly_dark", height=520)
    st.plotly_chart(fig, use_container_width=True)


def render_leaders(theme):
    rows = []
    for item in theme["global_universe"]:
        rows.append({
            "Company": item["name"],
            "Country": item["flag"],
            "Ticker": item["ticker"],
            "Mkt Cap ($B)": item.get("market_cap_usd_bn", None),
            "Thesis": item.get("thesis", ""),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    df["Mkt Cap ($B)"] = pd.to_numeric(df["Mkt Cap ($B)"], errors="coerce")
    plot_df = df.dropna(subset=["Mkt Cap ($B)"])
    if not plot_df.empty:
        fig = px.bar(plot_df, x="Company", y="Mkt Cap ($B)", color="Country",
                     title="Global leaders by market cap ($B)")
        fig.update_layout(template="plotly_dark", height=350)
        st.plotly_chart(fig, use_container_width=True)


def render_policy(theme):
    st.markdown("#### India Policy & Position")
    kpis = theme["policy_kpis"]
    if kpis:
        cols = st.columns(len(kpis))
        for c, kpi in zip(cols, kpis):
            c.metric(kpi["label"], kpi["value"], help=f"as of {kpi['as_of']}")

    tl = pd.DataFrame(theme["policy_timeline"])
    if not tl.empty:
        st.markdown("**Policy timeline**")
        st.dataframe(tl, use_container_width=True, hide_index=True)


def render_direct_indirect(theme):
    all_tickers = [x["ticker"] for x in theme["india_direct"] + theme["india_indirect"]]
    prices = batch_prices(tuple(all_tickers), period="2y")

    def enrich(items):
        rows = []
        for item in items:
            df = prices.get(item["ticker"])
            rsi = compute_rsi(df["Close"]) if df is not None and len(df) > 14 else np.nan
            r1y = compute_momentum(df["Close"], 252) if df is not None and len(df) > 252 else np.nan
            rows.append({
                "Name": item["name"],
                "Ticker": item["ticker"],
                "Link": item.get("link", item.get("link_type", "")),
                "Reason": item["reason"],
                "1Y %": f"{r1y:+.1f}%" if pd.notna(r1y) else "—",
                "RSI": f"{rsi:.0f}" if pd.notna(rsi) else "—",
            })
        return pd.DataFrame(rows)

    st.markdown("#### Indian Listed Companies — Direct vs. Indirect")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🟢 Direct plays**")
        st.dataframe(enrich(theme["india_direct"]), use_container_width=True, hide_index=True)
    with c2:
        st.markdown("**🟡 Indirect plays**")
        st.dataframe(enrich(theme["india_indirect"]), use_container_width=True, hide_index=True)


def render_network_graph(theme, theme_key):
    """Ecosystem network: center theme → direct (solid) → indirect (dashed)."""
    nodes = [{"name": theme_key, "x": 0.0, "y": 0.0, "type": "center", "size": 44}]

    direct = theme["india_direct"]
    indirect = theme["india_indirect"]

    for i, item in enumerate(direct):
        angle = 2 * math.pi * i / max(len(direct), 1)
        nodes.append({
            "name": item["name"],
            "x": 1.6 * math.cos(angle),
            "y": 1.6 * math.sin(angle),
            "type": "direct",
            "size": 26,
        })

    for i, item in enumerate(indirect):
        angle = 2 * math.pi * i / max(len(indirect), 1) + 0.4
        nodes.append({
            "name": item["name"],
            "x": 3.1 * math.cos(angle),
            "y": 3.1 * math.sin(angle),
            "type": "indirect",
            "size": 18,
        })

    fig = go.Figure()

    # Edges
    for n in nodes:
        if n["type"] == "direct":
            fig.add_trace(go.Scatter(
                x=[0, n["x"]], y=[0, n["y"]], mode="lines",
                line=dict(color="rgba(46, 204, 113, 0.55)", width=2),
                showlegend=False, hoverinfo="skip"
            ))
        elif n["type"] == "indirect":
            fig.add_trace(go.Scatter(
                x=[0, n["x"]], y=[0, n["y"]], mode="lines",
                line=dict(color="rgba(243, 156, 18, 0.45)", width=1, dash="dash"),
                showlegend=False, hoverinfo="skip"
            ))

    # Nodes by type
    type_colors = {"center": "#FFD700", "direct": "#2ECC71", "indirect": "#F39C12"}
    type_labels = {"center": "Theme (center)", "direct": "Direct play", "indirect": "Indirect play"}
    for ntype in ["center", "direct", "indirect"]:
        filtered = [n for n in nodes if n["type"] == ntype]
        if not filtered:
            continue
        fig.add_trace(go.Scatter(
            x=[n["x"] for n in filtered],
            y=[n["y"] for n in filtered],
            mode="markers+text",
            marker=dict(size=[n["size"] for n in filtered],
                        color=type_colors[ntype],
                        line=dict(width=1, color="white")),
            text=[n["name"] for n in filtered],
            textposition="top center",
            textfont=dict(size=10),
            name=type_labels[ntype],
            hoverinfo="text",
        ))

    fig.update_layout(
        template="plotly_dark", height=620,
        xaxis=dict(visible=False, range=[-4, 4]),
        yaxis=dict(visible=False, range=[-4, 4]),
        title="Ecosystem — Direct (solid green) vs Indirect (dashed orange)",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.1),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_correlation_heatmap(theme):
    """Correlation matrix of 1Y daily returns across all theme tickers."""
    all_tickers = (
        [x["ticker"] for x in theme["global_universe"]]
        + [x["ticker"] for x in theme["india_direct"]]
        + [x["ticker"] for x in theme["india_indirect"]]
    )
    prices = batch_prices(tuple(all_tickers), period="1y")

    if len(prices) < 3:
        st.info("Need at least 3 tickers with price data for correlation heatmap.")
        return

    closes = pd.DataFrame({t: prices[t]["Close"] for t in prices}).dropna()
    if len(closes.columns) < 3 or len(closes) < 30:
        st.info("Not enough overlapping price history for correlation.")
        return

    corr = closes.pct_change().corr().round(2)
    fig = px.imshow(
        corr, color_continuous_scale="RdYlGn", zmin=-1, zmax=1,
        text_auto=True, aspect="auto",
        title="1Y Daily Return Correlation — shows clusters of co-moving names"
    )
    fig.update_layout(template="plotly_dark",
                      height=max(500, 26 * len(corr.columns) + 150))
    st.plotly_chart(fig, use_container_width=True)


def render_risk_watchlist(theme):
    st.markdown("#### Risk Matrix & What to Track")
    risks = pd.DataFrame(theme["risks"])
    if not risks.empty:
        fig = px.scatter(
            risks, x="likelihood", y="impact", text="risk", color="category",
            title="Risk 2×2 (likelihood vs impact)",
            labels={"likelihood": "Likelihood (1-5)", "impact": "Impact (1-5)"},
        )
        fig.update_traces(textposition="top center", marker=dict(size=14))
        fig.update_layout(
            template="plotly_dark", height=420,
            xaxis=dict(range=[0.5, 5.5], dtick=1),
            yaxis=dict(range=[0.5, 5.5], dtick=1),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Watchlist**")
    st.dataframe(pd.DataFrame(theme["watchlist"]), use_container_width=True, hide_index=True)


def render_theme_briefing(theme_key):
    theme = THEMES[theme_key]
    st.subheader(f"📋 {theme_key} — Full Briefing")
    render_scorecard(theme)
    st.markdown("---")
    render_treemap(theme)
    st.markdown("---")
    render_leaders(theme)
    st.markdown("---")
    render_policy(theme)
    st.markdown("---")
    render_direct_indirect(theme)
    st.markdown("---")
    render_network_graph(theme, theme_key)
    st.markdown("---")
    render_correlation_heatmap(theme)
    st.markdown("---")
    render_risk_watchlist(theme)


# ============================================================
# THEME SEARCH FALLBACK
# ============================================================
def fuzzy_match(query, themes):
    lower_map = {}
    for k, t in themes.items():
        lower_map[k.lower()] = k
        for alias in t.get("aliases", []):
            lower_map[alias.lower()] = k
    matches = difflib.get_close_matches(query.lower(), list(lower_map.keys()),
                                        n=1, cutoff=0.6)
    if matches:
        return lower_map[matches[0]]
    return None


def search_universe(query):
    """Resolve a free-text query to a list of equity/ETF tickers."""
    tickers = []
    seen = set()
    try:
        search = yf.Search(query, max_results=30)
        for q in search.quotes:
            sym = q.get("symbol", "")
            qtype = q.get("quoteType", "")
            if not sym or sym in seen:
                continue
            if qtype not in ("EQUITY", "ETF", "MUTUALFUND"):
                continue
            seen.add(sym)
            tickers.append(sym)
    except Exception:
        pass
    return tickers[:15]


def render_auto_briefing(query):
    st.warning(f"⚠️ '{query}' is not in the curated registry. Showing quantitative-only view.")
    st.caption("Policy, direct/indirect rationale, and risk text are unavailable for uncurated topics. "
               "Add this theme to THEMES to unlock the full briefing.")

    tickers = search_universe(query)
    if not tickers:
        st.error("Could not resolve any tickers. Try a more specific keyword "
                 "(e.g., 'cybersecurity', 'quantum computing', 'space').")
        return

    st.markdown(f"**Resolved {len(tickers)} tickers:** "
                f"{', '.join(tickers[:10])}{'...' if len(tickers) > 10 else ''}")
    prices = batch_prices(tuple(tickers), period="1y")
    if not prices:
        st.error("No price data returned for the resolved tickers.")
        return

    rets_3m = [compute_momentum(df["Close"], 63) for df in prices.values() if len(df) > 63]
    rets_3m = [r for r in rets_3m if pd.notna(r)]
    above_200, valid_200 = 0, 0
    for df in prices.values():
        if len(df) >= 200:
            valid_200 += 1
            ma200 = df["Close"].rolling(200).mean().iloc[-1]
            if pd.notna(ma200) and df["Close"].iloc[-1] > ma200:
                above_200 += 1

    c1, c2, c3 = st.columns(3)
    c1.metric("Momentum (3M avg)", f"{np.mean(rets_3m):+.1f}%" if rets_3m else "—")
    c2.metric("Breadth (>200DMA)", f"{above_200/valid_200*100:.0f}%" if valid_200 else "—")
    c3.metric("Tickers resolved", len(prices))

    closes = pd.DataFrame({t: prices[t]["Close"] for t in prices}).dropna()
    if len(closes.columns) >= 3 and len(closes) > 30:
        corr = closes.pct_change().corr()
        fig = px.imshow(corr, color_continuous_scale="RdYlGn", zmin=-1, zmax=1,
                        title="Return correlation (1Y)")
        fig.update_layout(template="plotly_dark", height=500)
        st.plotly_chart(fig, use_container_width=True)


# ==========================================
# HELPERS FOR PORTFOLIO BUILDER
# ==========================================
def calc_max_drawdown(series):
    cum_ret = (1 + series).cumprod()
    peak = cum_ret.cummax()
    return ((cum_ret - peak) / peak).min()


def interpolate(risk, v1, v5, v10):
    if risk <= 5:
        return v1 + (v5 - v1) * (risk - 1) / 4
    return v5 + (v10 - v5) * (risk - 5) / 5


def cap_weights(weights, max_w):
    w = np.array(weights, dtype=float)
    while True:
        excess = np.sum(np.clip(w - max_w, 0, None))
        if excess < 1e-6:
            break
        w = np.clip(w, None, max_w)
        uncapped_mask = w < max_w
        if not np.any(uncapped_mask):
            break
        w[uncapped_mask] += excess * (w[uncapped_mask] / np.sum(w[uncapped_mask]))
    return w / np.sum(w)


# ==========================================
# MARKET DRIVERS
# ==========================================
with st.expander("🚨 Current Market Drivers & Risks", expanded=False):
    current_topics = [
        {"Topic": "FPI Flows", "Detail": "Monitor foreign portfolio investment flows.", "Market Impact": "⚪ Verify latest data"},
        {"Topic": "Inflation & RBI Rates", "Detail": "Higher inflation and rates can pressure valuations.", "Market Impact": "⚪ Monitor"},
        {"Topic": "Crude Oil & Geopolitics", "Detail": "Higher crude prices can increase India's import bill.", "Market Impact": "⚪ Monitor"},
        {"Topic": "Global Technology", "Detail": "Global technology sentiment can influence Indian IT stocks.", "Market Impact": "⚪ Monitor"},
        {"Topic": "Earnings & Valuations", "Detail": "Track earnings growth against market valuations.", "Market Impact": "⚪ Monitor"},
    ]
    st.dataframe(pd.DataFrame(current_topics), use_container_width=True, hide_index=True)

# ==========================================
# AUTOMATED SCAN TIMESTAMP
# ==========================================
@st.cache_data(ttl=60)
def get_last_scan():
    try:
        url = "https://raw.githubusercontent.com/prabhakarj2001/Khaata/main/scan_status.json"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json().get("last_scan", "Not available")
    except Exception:
        return "Not available"


# ==========================================
# TELEGRAM
# ==========================================
def send_telegram_message(token, chat_id, message):
    if not token or not chat_id:
        return False, "Add TG_TOKEN and TG_CHAT_ID in Streamlit Secrets."
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        lines = message.split("\n")
        chunks = []
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > 3900:
                chunks.append(current)
                current = ""
            current += line + "\n"
        if current.strip():
            chunks.append(current)
        for chunk in chunks:
            response = requests.post(
                url,
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"},
                timeout=15,
            )
            result = response.json()
            if not result.get("ok"):
                return False, result.get("description", "Telegram error")
        return True, "Sent successfully"
    except Exception as e:
        return False, str(e)


SIGNAL_ORDER = ["STRONG SELL", "STRONG BUY", "WEAK SELL", "WEAK BUY"]
SIGNAL_EMOJI = {
    "STRONG SELL": "🔴",
    "STRONG BUY": "🟢",
    "WEAK SELL": "🟠",
    "WEAK BUY": "🟡",
}


def allocate_alerts(sig_list, cap):
    groups = {
        k: sorted([s for s in sig_list if s["Type"] == k],
                  key=lambda x: x["Impact"], reverse=True)
        for k in SIGNAL_ORDER
    }
    picked = {k: [] for k in SIGNAL_ORDER}
    picked["STRONG SELL"] = groups["STRONG SELL"][:cap]
    remaining = cap - len(picked["STRONG SELL"])
    others = ["STRONG BUY", "WEAK SELL", "WEAK BUY"]
    pools = {k: list(groups[k]) for k in others}
    while remaining > 0 and any(pools[k] for k in others):
        active = [k for k in others if pools[k]]
        share = max(1, remaining // len(active))
        for k in active:
            take = min(share, len(pools[k]), remaining)
            picked[k] += pools[k][:take]
            pools[k] = pools[k][take:]
            remaining -= take
            if remaining == 0:
                break
    return picked, groups


def build_alert_message(sig_list, cap):
    picked, groups = allocate_alerts(sig_list, cap)
    shown = sum(len(v) for v in picked.values())
    msg = f"<b>🚨 Buy/Sell Alerts</b> ({shown} of {len(sig_list)} shown)\n"
    for k in SIGNAL_ORDER:
        if not picked[k]:
            continue
        extra = len(groups[k]) - len(picked[k])
        more = f" (+{extra} more)" if extra > 0 else ""
        msg += f"\n<b>{SIGNAL_EMOJI[k]} {k}{more}</b>\n"
        for s in picked[k]:
            msg += f"• {s['Stock']} ₹{s['Price']} | RSI {s['RSI']} | {s['Hold Time']}\n"
    return msg


# ==========================================
# SIDEBAR
# ==========================================
st.sidebar.header("📱 Telegram Alerts")
try:
    tg_token = st.secrets["TG_TOKEN"]
    tg_chat_id = st.secrets["TG_CHAT_ID"]
except Exception:
    tg_token = ""
    tg_chat_id = ""
    st.sidebar.warning("Configure Telegram credentials in Streamlit Secrets.")

tg_cap = st.sidebar.slider("Maximum stocks per alert", 10, 100, 30, step=5)


# ==========================================
# DATA FETCHING
# ==========================================
@st.cache_data(ttl=86400)
def get_nse_data():
    try:
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))
        return df["Symbol"].tolist(), dict(zip(df["Symbol"], df["Industry"]))
    except Exception:
        fallback = ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"]
        return fallback, {s: "Unknown" for s in fallback}


def get_ret(df, days):
    if len(df) <= 1:
        return 0.0
    actual_days = min(days, len(df) - 1)
    old_price = df["Close"].iloc[-(actual_days + 1)]
    current_price = df["Close"].iloc[-1]
    if pd.isna(old_price) or old_price == 0:
        return 0.0
    return ((current_price - old_price) / old_price) * 100


@st.cache_data(ttl=3600)
def download_data(symbols, period="5y"):
    all_data = {}
    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i + 50]
        tickers = [s if s.endswith(".NS") else s + ".NS" for s in chunk]
        try:
            data = yf.download(tickers, period=period, interval="1d",
                               group_by="ticker", progress=False, threads=True,
                               auto_adjust=True)
            if data.empty:
                continue
            for orig_sym, clean_sym in zip(chunk, tickers):
                if (isinstance(data.columns, pd.MultiIndex)
                        and clean_sym in data.columns.get_level_values(0)):
                    df_stock = data[clean_sym].dropna()
                elif not isinstance(data.columns, pd.MultiIndex) and len(chunk) == 1:
                    df_stock = data.dropna()
                else:
                    continue
                if not df_stock.empty:
                    all_data[orig_sym.replace(".NS", "")] = df_stock
        except Exception:
            continue
    return all_data


@st.cache_data(ttl=3600)
def get_metals(period="5y"):
    out = {}
    for name, ticker in METALS.items():
        try:
            d = yf.download(ticker, period=period, interval="1d",
                            progress=False, auto_adjust=True)
            if d.empty:
                continue
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.get_level_values(0)
            out[name] = d.dropna()
        except Exception:
            continue
    return out


# ==========================================
# SCANNER ENGINE
# ==========================================
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Scanner Settings")
min_history = st.sidebar.slider("Minimum trading history (days)", 30, 200, 50)

if st.button("🚀 Fetch Nifty 500 Data & Build Dashboard", type="primary"):
    all_syms, nse_map = get_nse_data()
    all_syms = [s for s in all_syms if "&" not in s]
    progress = st.progress(0)
    status = st.empty()
    status.info(f"Downloading data for {len(all_syms)} stocks...")
    p_data = download_data(all_syms, period="5y")
    results = []

    for index, sym in enumerate(all_syms):
        df_stock = p_data.get(sym)
        if df_stock is None or len(df_stock) < min_history:
            continue
        try:
            price = float(df_stock["Close"].iloc[-1])
            returns = {p: get_ret(df_stock, days) for p, days in PERIODS.items()}
            momentum = (returns["1M"] * 0.2 + returns["6M"] * 0.3 + returns["1Y"] * 0.5)
            ma50 = df_stock["Close"].rolling(50).mean().iloc[-1]
            ma200 = df_stock["Close"].rolling(200).mean().iloc[-1]
            trend = "🟢 Up" if price > ma50 else "🔴 Down"
            if pd.notna(ma200):
                long_trend = "🟢 Bullish" if price > ma200 else "🔴 Bearish"
            else:
                long_trend = "⚪ Insufficient data"
            avg_volume = df_stock["Volume"].rolling(20).mean().iloc[-1]
            current_volume = df_stock["Volume"].iloc[-1]
            volume_ratio = (current_volume / avg_volume
                            if pd.notna(avg_volume) and avg_volume > 0 else 0)
            volume_status = ("🚨 SPIKE" if volume_ratio >= 2 else "Normal")
            row = {
                "Stock": sym, "Sector": nse_map.get(sym, "Unknown"),
                "Price": round(price, 2), "Momentum": round(float(momentum), 1),
                "Trend": trend, "Long Trend": long_trend,
                "Volume": round(float(volume_ratio), 2), "Vol": volume_status,
            }
            for p in PERIODS:
                row[f"{p} %"] = round(float(returns[p]), 1)
            results.append(row)
        except Exception:
            continue
        progress.progress((index + 1) / len(all_syms))

    st.session_state.df = pd.DataFrame(results)
    st.session_state.p_data = p_data
    status.empty()
    progress.empty()
    st.success(f"Successfully scanned {len(results)} stocks.")


# ==========================================
# DASHBOARD
# ==========================================
if ("df" in st.session_state and not st.session_state.df.empty):
    df = st.session_state.df
    st.markdown(f"**Last automated scan:** {get_last_scan()}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Stocks Scanned", len(df))
    c2.metric("Bullish Stocks", int((df["Trend"] == "🟢 Up").sum()))
    c3.metric("Bearish Stocks", int((df["Trend"] == "🔴 Down").sum()))
    c4.metric("Volume Spikes", int((df["Vol"] == "🚨 SPIKE").sum()))

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab_hot, tab_search = st.tabs([
        "📉 Sensex",
        "🏆 Top 10",
        "📊 Scanner",
        "🏢 Sectors",
        "🥇 Metals",
        "📈 Buy/Sell",
        "💼 Portfolio Builder",
        "🔥 Hot Themes",
        "🔍 Theme Search",
    ])

    # SENSEX
    with tab1:
        st.subheader("Sensex Performance")
        s_df = yf.download("^BSESN", period="1y", interval="1d",
                           progress=False, auto_adjust=True)
        if not s_df.empty:
            if isinstance(s_df.columns, pd.MultiIndex):
                s_df.columns = s_df.columns.get_level_values(0)
            fig_s = go.Figure(data=[go.Candlestick(
                x=s_df.index, open=s_df["Open"], high=s_df["High"],
                low=s_df["Low"], close=s_df["Close"],
            )])
            fig_s.update_layout(template="plotly_dark",
                                xaxis_rangeslider_visible=False, height=450)
            st.plotly_chart(fig_s, use_container_width=True)
        else:
            st.warning("Sensex data unavailable.")

    # TOP 10
    with tab2:
        st.subheader("🏆 Top 10 Multi-Period Performers")
        top10 = df.nlargest(10, "Momentum")
        st.dataframe(
            top10[["Stock", "Sector", "Price", "1M %", "3M %", "6M %",
                   "1Y %", "3Y %", "5Y %", "Momentum", "Trend"]],
            use_container_width=True, hide_index=True,
        )

    # SCANNER
    with tab3:
        st.subheader(f"Full Market Scanner ({len(df)} stocks)")
        sector_filter = st.multiselect("Filter by sector",
                                       sorted(df["Sector"].dropna().unique()))
        trend_filter = st.multiselect("Filter by trend", ["🟢 Up", "🔴 Down"])
        filtered = df.copy()
        if sector_filter:
            filtered = filtered[filtered["Sector"].isin(sector_filter)]
        if trend_filter:
            filtered = filtered[filtered["Trend"].isin(trend_filter)]
        st.dataframe(
            filtered.sort_values(["Vol", "Momentum"], ascending=[False, False]),
            use_container_width=True, hide_index=True,
        )
        st.download_button("⬇️ Download Scanner CSV",
                           filtered.to_csv(index=False),
                           file_name="market_scanner.csv", mime="text/csv")

    # SECTORS
    with tab4:
        st.subheader("Sector Performance")
        sel_p = st.select_slider("Timeline", options=list(PERIODS.keys()),
                                 value="1Y", key="sec_period")
        col = f"{sel_p} %"
        sec_perf = (df.groupby("Sector")[col].mean().reset_index()
                    .sort_values(by=col, ascending=False))
        fig = px.bar(sec_perf, x="Sector", y=col, color=col,
                     color_continuous_scale="RdYlGn", color_continuous_midpoint=0,
                     title=f"Sector Average Return ({sel_p})")
        fig.update_layout(template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("**Sector performance across all timelines**")
        heat = df.groupby("Sector")[[f"{p} %" for p in PERIODS]].mean().round(1)
        heat = heat.sort_values(by=col, ascending=False)
        fig_h = px.imshow(heat, color_continuous_scale="RdYlGn",
                          color_continuous_midpoint=0, aspect="auto", text_auto=True)
        fig_h.update_layout(template="plotly_dark",
                            height=max(350, 28 * len(heat) + 100))
        st.plotly_chart(fig_h, use_container_width=True)

        sel = st.selectbox("Drill Down Sector",
                           sec_perf["Sector"].tolist(), key="sec_drill")
        if sel:
            st.dataframe(df[df["Sector"] == sel].sort_values(by=col, ascending=False),
                         use_container_width=True, hide_index=True)

    # METALS
    with tab5:
        st.subheader("🥇 Metals & Market Momentum")
        metal_data = get_metals("5y")
        if metal_data:
            flow_data = []
            for name, d in metal_data.items():
                rsi = ta.momentum.RSIIndicator(d["Close"], window=14).rsi().iloc[-1]
                status = ("🔴 Overbought" if rsi > 70
                          else "🟢 Oversold" if rsi < 30 else "⚪ Neutral")
                row = {"Metal": name, "Price": round(float(d["Close"].iloc[-1]), 2)}
                for p, days in PERIODS.items():
                    row[f"{p} %"] = round(float(get_ret(d, days)), 1)
                row.update({"RSI": round(float(rsi), 1), "Momentum Status": status})
                flow_data.append(row)
            st.dataframe(pd.DataFrame(flow_data),
                         use_container_width=True, hide_index=True)

            m_p = st.select_slider("Chart timeline", options=list(PERIODS.keys()),
                                   value="1Y", key="metal_period")
            n = PERIODS[m_p]
            fig_m = go.Figure()
            for name, d in metal_data.items():
                w = d["Close"].tail(n + 1)
                if len(w) > 1:
                    fig_m.add_trace(go.Scatter(
                        x=w.index, y=(w / w.iloc[0]) * 100,
                        mode="lines", name=name,
                    ))
            fig_m.update_layout(title=f"Metals ({m_p} trend, rebased to 100)",
                                template="plotly_dark", height=400)
            st.plotly_chart(fig_m, use_container_width=True)
        else:
            st.warning("Metals data unavailable.")

    # BUY / SELL
    with tab6:
        st.subheader("📈 Actionable Signals & Hold Times")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📤 Send Top 10 Momentum Report"):
                top10 = df.nlargest(10, "Momentum")
                msg = "<b>🚨 Market Momentum Report</b>\n\n"
                for _, r in top10.iterrows():
                    msg += f"• {r['Stock']} (Score: {r['Momentum']}) ₹{r['Price']}\n"
                success, err = send_telegram_message(tg_token, tg_chat_id, msg)
                if success:
                    st.success("Report sent to Telegram.")
                else:
                    st.error(err)
        with col2:
            if st.button("📅 Send Weekly Update"):
                top10 = df.nlargest(10, "1M %")
                msg = "<b>📅 Top 10 Stocks by 1M Return</b>\n\n"
                for _, r in top10.iterrows():
                    msg += f"• {r['Stock']}: {r['1M %']}% (₹{r['Price']})\n"
                success, err = send_telegram_message(tg_token, tg_chat_id, msg)
                if success:
                    st.success("Weekly report sent.")
                else:
                    st.error(err)

        st.markdown("---")
        if st.button("🔄 Generate Buy/Sell Alerts"):
            sig_list = []
            p_data = st.session_state.p_data
            progress = st.progress(0)
            stocks = df["Stock"].tolist()
            for i, stock in enumerate(stocks):
                df_h = p_data.get(stock)
                if df_h is None or len(df_h) < 30:
                    continue
                try:
                    close = df_h["Close"]
                    rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]
                    macd = ta.trend.MACD(close)
                    ml = macd.macd().iloc[-1]
                    ms = macd.macd_signal().iloc[-1]
                    stock_row = df[df["Stock"] == stock].iloc[0]
                    mom_score = stock_row["Momentum"]
                    if rsi < 40 and ml > ms:
                        typ = "STRONG BUY"
                        hold = "1-2 Months" if mom_score > 15 else "2-3 Weeks"
                        why = "Low RSI and bullish MACD"
                    elif rsi < 40:
                        typ = "WEAK BUY"
                        hold = "Wait for MACD confirmation"
                        why = "Low RSI"
                    elif rsi > 60 and ml < ms:
                        typ = "STRONG SELL"
                        hold = "Review exit"
                        why = "High RSI and bearish MACD"
                    elif rsi > 60:
                        typ = "WEAK SELL"
                        hold = "Consider partial profit"
                        why = "High RSI"
                    else:
                        continue
                    impact = (abs(rsi - 50) + abs(mom_score) * 0.5 +
                              (10 if stock_row["Vol"] == "🚨 SPIKE" else 0))
                    sig_list.append({
                        "Stock": stock, "Price": round(float(close.iloc[-1]), 2),
                        "RSI": round(float(rsi), 1), "Type": typ,
                        "Action": f"{SIGNAL_EMOJI[typ]} {typ}",
                        "Hold Time": hold, "Impact": round(float(impact), 1),
                        "Why?": why,
                    })
                except Exception:
                    continue
                progress.progress((i + 1) / len(stocks))
            progress.empty()

            if sig_list:
                sig_df = pd.DataFrame(sig_list)
                sig_df["_order"] = sig_df["Type"].map(
                    {k: i for i, k in enumerate(SIGNAL_ORDER)}
                )
                sig_df = (sig_df.sort_values(["_order", "Impact"],
                                             ascending=[True, False])
                          .drop(columns=["_order"]))
                st.session_state.sig_df = sig_df
                success, err = send_telegram_message(
                    tg_token, tg_chat_id, build_alert_message(sig_list, tg_cap)
                )
                if success:
                    st.success("Buy/Sell alerts sent to Telegram.")
                else:
                    st.error(f"Telegram error: {err}")
            else:
                st.info("No signals generated. Market conditions are neutral.")

        if "sig_df" in st.session_state:
            st.subheader("Generated Signals")
            st.dataframe(st.session_state.sig_df,
                         use_container_width=True, hide_index=True)
            st.download_button("⬇️ Download Signals CSV",
                               st.session_state.sig_df.to_csv(index=False),
                               file_name="buy_sell_signals.csv", mime="text/csv")

    # PORTFOLIO BUILDER
    with tab7:
        st.subheader("💼 Portfolio Builder")
        st.caption("Not investment advice. This is a quantitative allocation tool.")

        col_in1, col_in2, col_in3 = st.columns(3)
        with col_in1:
            inv_amount = st.number_input("Investment Amount (₹)", min_value=25000,
                                         value=500000, step=25000, key="pb_amount")
        with col_in2:
            horizon = st.select_slider("Horizon",
                                       options=["Under 6 months", "6-24 months", "3+ years"],
                                       value="6-24 months", key="pb_horizon")
        with col_in3:
            risk = st.slider("Risk Tolerance (1-10)", 1, 10, 5, key="pb_risk")
            risk_label = "Averse" if risk <= 3 else ("Balanced" if risk <= 7 else "Aggressive")
            st.write(f"Profile: **{risk_label}**")

        if st.button("Build Portfolio", key="pb_build_btn"):
            try:
                num_pos = int(interpolate(risk, 18, 13, 10))
                max_w = interpolate(risk, 0.07, 0.10, 0.15)
                max_sec_w = interpolate(risk, 0.20, 0.25, 0.35)
                vol_cap = interpolate(risk, 0.25, 0.40, 1.0)
                liq_floor = interpolate(risk, 50, 20, 10)
                stop_mult = interpolate(risk, 3.0, 2.5, 2.0)
                cash_buffer = interpolate(risk, 0.10, 0.05, 0.0)

                if risk <= 3:
                    core_pct = 0.50
                elif risk <= 7:
                    core_pct = 0.25
                else:
                    core_pct = interpolate(risk, 0, 0.10, 0)

                gold_pct = 0.0
                try:
                    gold_df = yf.download("GC=F", period="1y", interval="1d", progress=False)
                    if not gold_df.empty:
                        if isinstance(gold_df.columns, pd.MultiIndex):
                            gold_df.columns = gold_df.columns.get_level_values(0)
                        if len(gold_df) >= 200:
                            gold_close = gold_df['Close'].squeeze()
                            gold_sma = gold_close.rolling(200).mean().iloc[-1]
                            gold_trend_up = bool(gold_close.iloc[-1] > gold_sma)
                            if gold_trend_up and risk <= 5:
                                gold_pct = 0.10
                except Exception:
                    pass

                st.write("**Risk Parameters Applied:**")
                params_dict = {
                    "Positions": num_pos,
                    "Max Stock %": f"{max_w*100:.1f}%",
                    "Max Sector %": f"{max_sec_w*100:.1f}%",
                    "Vol Cap": "None" if vol_cap >= 1.0 else f"{vol_cap*100:.0f}%",
                    "Liq Floor (₹Cr)": f"{liq_floor:.0f}",
                    "Stop Mult": f"{stop_mult:.1f}x ATR",
                    "Cash Buffer": f"{cash_buffer*100:.0f}%",
                    "Core ETF": f"{core_pct*100:.0f}%",
                    "Gold Sleeve": f"{gold_pct*100:.0f}%",
                }
                st.dataframe(pd.DataFrame([params_dict]), hide_index=True)

                eligible = []
                p_data_local = st.session_state.p_data
                for _, row in df.iterrows():
                    sym = row['Stock']
                    df_p = p_data_local.get(sym)
                    if df_p is None or len(df_p) < 252:
                        continue
                    vol_1y = df_p['Close'].pct_change().tail(252).std() * np.sqrt(252)
                    liq_cr = (df_p['Close'] * df_p['Volume']).tail(20).mean() / 10000000
                    above_200 = bool(row.get('Long Trend') == "🟢 Bullish")
                    relax_a = relax_b = relax_c = relax_d = False
                    while True:
                        pass_vol = vol_1y <= vol_cap if not relax_a else vol_1y <= (vol_cap + 0.10)
                        pass_liq = liq_cr >= liq_floor if not relax_b else liq_cr >= (liq_floor / 2)
                        pass_rs = row['3M %'] > 0 if not relax_c else True
                        pass_above200 = above_200 if not relax_d else True
                        if pass_vol and pass_liq and pass_rs and pass_above200:
                            break
                        if not relax_a:
                            relax_a = True
                        elif not relax_b:
                            relax_b = True
                        elif not relax_c:
                            relax_c = True
                        elif not relax_d:
                            relax_d = True
                        else:
                            break

                    if pass_vol and pass_liq and pass_rs and pass_above200:
                        score = 0
                        rsi = ta.momentum.RSIIndicator(df_p['Close'], window=14).rsi().iloc[-1]
                        if horizon == "Under 6 months":
                            pullback = 1 if 30 <= rsi <= 50 and above_200 else 0
                            score = (0.4 * pullback
                                     + 0.3 * (row['3M %'] / 100)
                                     + 0.3 * (1 if row['Trend'] == "🟢 Up" else 0))
                        elif horizon == "6-24 months":
                            score = (0.5 * (row['Momentum'] / 100)
                                     + 0.25 * (row['6M %'] / 100)
                                     + 0.25 * (1 if row['Trend'] == "🟢 Up" else 0))
                        else:
                            consistency = ((1 if row['1Y %'] > 0 else 0)
                                           + (1 if row['3Y %'] > 0 else 0)
                                           + (1 if row['5Y %'] > 0 else 0))
                            max_dd = calc_max_drawdown(df_p['Close'].pct_change().tail(756))
                            score = (0.35 * (consistency / 3)
                                     + 0.35 * (1 - abs(max_dd))
                                     + 0.30 * (1 - vol_1y))
                        low_vol_score = 1 - vol_1y
                        vol_weight = ((10 - risk) / 10) * 0.4
                        score = (score * (1 - vol_weight) + low_vol_score * vol_weight)
                        if risk >= 8:
                            score += (row['Momentum'] / 100) * 0.2
                        eligible.append({
                            "Stock": sym, "Sector": row['Sector'],
                            "Price": row['Price'], "Score": score,
                            "Vol": vol_1y, "Liq": liq_cr, "RSI": rsi,
                            "RS_3M": row['3M %'],
                            "ATR": ta.volatility.AverageTrueRange(
                                df_p['High'], df_p['Low'], df_p['Close']
                            ).average_true_range().iloc[-1],
                        })

                if len(eligible) < 10:
                    st.warning("Not enough stocks passed strict filters. Relaxed filters applied.")

                df_elig = pd.DataFrame(eligible).sort_values(by="Score", ascending=False)
                selected = []
                sector_counts = {}
                for _, row in df_elig.iterrows():
                    sec = row['Sector']
                    if sector_counts.get(sec, 0) < math.floor(max_sec_w * num_pos):
                        selected.append(row)
                        sector_counts[sec] = sector_counts.get(sec, 0) + 1
                    if len(selected) >= num_pos:
                        break

                df_sel = pd.DataFrame(selected)
                df_sel['InvVol'] = 1 / df_sel['Vol']
                df_sel['Weight'] = df_sel['InvVol'] / df_sel['InvVol'].sum()
                df_sel['Weight'] = cap_weights(df_sel['Weight'].tolist(), max_w)

                breadth = (df['Long Trend'] == "🟢 Bullish").sum() / len(df) * 100
                if breadth < 40:
                    cash_buffer += 0.20
                if breadth < 25:
                    cash_buffer += 0.40
                cash_buffer = min(cash_buffer, 1.0 - core_pct - gold_pct)

                equity_sleeve = 1 - core_pct - gold_pct - cash_buffer
                equity_amt = inv_amount * equity_sleeve
                core_amt = inv_amount * core_pct
                gold_amt = inv_amount * gold_pct
                cash_amt = inv_amount * cash_buffer

                df_sel['Amt'] = df_sel['Weight'] * equity_amt
                df_sel['Shares'] = np.floor(df_sel['Amt'] / df_sel['Price']).astype(int)
                df_sel['Invested'] = df_sel['Shares'] * df_sel['Price']
                df_sel['Stop'] = df_sel['Price'] - (stop_mult * df_sel['ATR'])

                st.write("### Summary")
                col_s1, col_s2, col_s3 = st.columns(3)
                col_s1.metric("Total Capital", f"₹{inv_amount:,.0f}")
                col_s2.metric("Equity Invested", f"₹{df_sel['Invested'].sum():,.0f}")
                col_s3.metric("Core + Gold + Cash",
                              f"₹{core_amt + gold_amt + cash_amt:,.0f}")

                fig_pie = px.pie(
                    values=[df_sel['Invested'].sum(), core_amt, gold_amt, cash_amt],
                    names=['Equity', 'Core ETF', 'Gold', 'Cash'], hole=0.5,
                )
                st.plotly_chart(fig_pie, use_container_width=True)

                st.write("### Reality Check (Historical Risk)")
                try:
                    nifty_df = yf.download("^NSEI", period="5y", interval="1d",
                                           progress=False)
                    if isinstance(nifty_df.columns, pd.MultiIndex):
                        nifty_df.columns = nifty_df.columns.get_level_values(0)
                    nifty_close = nifty_df['Close'].squeeze().dropna()

                    p_closes = pd.DataFrame({
                        row['Stock']: p_data_local[row['Stock']]['Close']
                        for _, row in df_sel.iterrows()
                    }).dropna()
                    p_rets = (p_closes.pct_change()
                              * df_sel.set_index('Stock')['Weight']).sum(axis=1).dropna()
                    nifty_rets = nifty_close.pct_change().tail(len(p_rets)).dropna()
                    p_rets = p_rets.tail(len(nifty_rets))

                    cum_ret = (1 + p_rets).cumprod()
                    roll_1m = (cum_ret / cum_ret.shift(21) - 1).min()
                    roll_3m = (cum_ret / cum_ret.shift(63) - 1).min()
                    max_dd = calc_max_drawdown(p_rets)
                    ann_vol = p_rets.std() * np.sqrt(252)
                    beta = np.cov(p_rets, nifty_rets)[0, 1] / np.var(nifty_rets)

                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("Worst 1M", f"{roll_1m*100:.1f}%",
                              f"₹{roll_1m*equity_amt:,.0f}")
                    c2.metric("Worst 3M", f"{roll_3m*100:.1f}%",
                              f"₹{roll_3m*equity_amt:,.0f}")
                    c3.metric("Max Drawdown", f"{max_dd*100:.1f}%",
                              f"₹{max_dd*equity_amt:,.0f}")
                    c4.metric("Ann. Volatility", f"{ann_vol*100:.1f}%")
                    c5.metric("Beta", f"{beta:.2f}")
                    st.caption("Historical risk of today's picks. "
                               "NOT a return forecast (look-ahead bias).")
                except Exception as e:
                    st.warning(f"Could not compute backtest: {e}")

                df_display = df_sel[['Stock', 'Sector', 'Price', 'Weight', 'Shares',
                                     'Invested', 'Stop', 'Momentum', '3M %', 'RSI']].copy()
                df_display['Weight'] = df_display['Weight'].apply(lambda x: f"{x*100:.1f}%")
                df_display['Stop'] = df_display['Stop'].round(1)
                st.dataframe(df_display, hide_index=True, use_container_width=True)

                if st.button("📤 Send Plan to Telegram"):
                    msg = f"<b>💼 Portfolio Plan (₹{inv_amount:,.0f})</b>\nRisk: {risk}\n\n"
                    for _, r in df_sel.iterrows():
                        msg += (f"• <b>{r['Stock']}</b>: {r['Shares']} sh @ "
                                f"₹{r['Price']} (Stop: ₹{r['Stop']:.1f})\n")
                    success, err = send_telegram_message(tg_token, tg_chat_id, msg)
                    if success:
                        st.success("✅ Sent to Telegram!")
                    else:
                        st.error(f"❌ Error: {err}")

            except Exception as e:
                st.error(f"❌ Failed to build portfolio: {e}")

    # ============================================================
    # NEW TAB: 🔥 HOT THEMES
    # ============================================================
    with tab_hot:
        st.subheader("🔥 Hot Themes — Click a Theme for Full Briefing")
        if not THEMES:
            st.info("No themes in registry. Add themes to THEMES dict.")
        else:
            try:
                choice = st.pills("Pick a hot theme", list(THEMES.keys()), default=None)
            except AttributeError:
                st.warning("st.pills requires Streamlit >= 1.40. Falling back to selectbox.")
                choice = st.selectbox("Pick a hot theme", ["—"] + list(THEMES.keys()))
                choice = None if choice == "—" else choice

            if choice:
                render_theme_briefing(choice)
            else:
                st.info("👆 Click a pill above to load the full briefing.")

    # ============================================================
    # NEW TAB: 🔍 THEME SEARCH
    # ============================================================
    with tab_search:
        st.subheader("🔍 Theme Search — Any Topic")
        query = st.text_input(
            "Enter any theme or keyword",
            placeholder="e.g. Quantum Computing, Cybersecurity, Space",
        )
        if query:
            matched = fuzzy_match(query, THEMES)
            if matched:
                st.success(f"Matched curated theme: **{matched}**")
                render_theme_briefing(matched)
            else:
                render_auto_briefing(query)
        else:
            st.info("Type a theme above. Curated themes get the full 6-view briefing; "
                    "uncurated themes get a quantitative-only view.")

else:
    st.info("Click the button above to download market data and build your scanner.")
