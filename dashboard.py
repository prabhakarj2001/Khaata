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

# ==========================================
# HELPERS FOR PORTFOLIO BUILDER
# ==========================================
def calc_max_drawdown(series):
    cum_ret = (1 + series).cumprod()
    peak = cum_ret.cummax()
    return ((cum_ret - peak) / peak).min()

def interpolate(risk, v1, v5, v10):
    if risk <= 5: return v1 + (v5 - v1) * (risk - 1) / 4
    return v5 + (v10 - v5) * (risk - 5) / 5

def cap_weights(weights, max_w):
    w = np.array(weights, dtype=float)
    while True:
        excess = np.sum(np.clip(w - max_w, 0, None))
        if excess < 1e-6: break
        w = np.clip(w, None, max_w)
        uncapped_mask = w < max_w
        if not np.any(uncapped_mask): break
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
        {"Topic": "Earnings & Valuations", "Detail": "Track earnings growth against market valuations.", "Market Impact": "⚪ Monitor"}
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
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "HTML"
                },
                timeout=15
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
    "WEAK BUY": "🟡"
}


def allocate_alerts(sig_list, cap):
    groups = {
        k: sorted(
            [s for s in sig_list if s["Type"] == k],
            key=lambda x: x["Impact"],
            reverse=True
        )
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

    msg = (
        f"<b>🚨 Buy/Sell Alerts</b> "
        f"({shown} of {len(sig_list)} shown)\n"
    )

    for k in SIGNAL_ORDER:
        if not picked[k]:
            continue

        extra = len(groups[k]) - len(picked[k])
        more = f" (+{extra} more)" if extra > 0 else ""

        msg += f"\n<b>{SIGNAL_EMOJI[k]} {k}{more}</b>\n"

        for s in picked[k]:
            msg += (
                f"• {s['Stock']} ₹{s['Price']} | "
                f"RSI {s['RSI']} | {s['Hold Time']}\n"
            )

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

tg_cap = st.sidebar.slider(
    "Maximum stocks per alert",
    10, 100, 30, step=5
)

# ==========================================
# DATA FETCHING
# ==========================================
@st.cache_data(ttl=86400)
def get_nse_data():
    try:
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"

        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        )

        response.raise_for_status()

        df = pd.read_csv(io.StringIO(response.text))

        return (
            df["Symbol"].tolist(),
            dict(zip(df["Symbol"], df["Industry"]))
        )

    except Exception:
        fallback = [
            "RELIANCE", "TCS", "HDFCBANK",
            "ICICIBANK", "INFY"
        ]

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

        tickers = [
            s if s.endswith(".NS") else s + ".NS"
            for s in chunk
        ]

        try:
            data = yf.download(
                tickers,
                period=period,
                interval="1d",
                group_by="ticker",
                progress=False,
                threads=True,
                auto_adjust=True
            )

            if data.empty:
                continue

            for orig_sym, clean_sym in zip(chunk, tickers):

                if (
                    isinstance(data.columns, pd.MultiIndex)
                    and clean_sym in data.columns.get_level_values(0)
                ):
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
            d = yf.download(
                ticker,
                period=period,
                interval="1d",
                progress=False,
                auto_adjust=True
            )

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

min_history = st.sidebar.slider(
    "Minimum trading history (days)",
    30, 200, 50
)

if st.button("🚀 Fetch Nifty 500 Data & Build Dashboard", type="primary"):

    all_syms, nse_map = get_nse_data()

    all_syms = [
        s for s in all_syms
        if "&" not in s
    ]

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

            returns = {
                p: get_ret(df_stock, days)
                for p, days in PERIODS.items()
            }

            momentum = (
                returns["1M"] * 0.2
                + returns["6M"] * 0.3
                + returns["1Y"] * 0.5
            )

            ma50 = df_stock["Close"].rolling(50).mean().iloc[-1]
            ma200 = df_stock["Close"].rolling(200).mean().iloc[-1]

            trend = "🟢 Up" if price > ma50 else "🔴 Down"

            if pd.notna(ma200):
                long_trend = "🟢 Bullish" if price > ma200 else "🔴 Bearish"
            else:
                long_trend = "⚪ Insufficient data"

            avg_volume = df_stock["Volume"].rolling(20).mean().iloc[-1]
            current_volume = df_stock["Volume"].iloc[-1]

            volume_ratio = (
                current_volume / avg_volume
                if pd.notna(avg_volume) and avg_volume > 0
                else 0
            )

            volume_status = (
                "🚨 SPIKE" if volume_ratio >= 2
                else "Normal"
            )

            row = {
                "Stock": sym,
                "Sector": nse_map.get(sym, "Unknown"),
                "Price": round(price, 2),
                "Momentum": round(float(momentum), 1),
                "Trend": trend,
                "Long Trend": long_trend,
                "Volume": round(float(volume_ratio), 2),
                "Vol": volume_status
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

    st.success(
        f"Successfully scanned {len(results)} stocks."
    )


# ==========================================
# DASHBOARD
# ==========================================
if (
    "df" in st.session_state
    and not st.session_state.df.empty
):

    df = st.session_state.df

    st.markdown(f"**Last automated scan:** {get_last_scan()}")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Stocks Scanned", len(df))
    c2.metric("Bullish Stocks", int((df["Trend"] == "🟢 Up").sum()))
    c3.metric("Bearish Stocks", int((df["Trend"] == "🔴 Down").sum()))
    c4.metric("Volume Spikes", int((df["Vol"] == "🚨 SPIKE").sum()))

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📉 Sensex",
        "🏆 Top 10",
        "📊 Scanner",
        "🏢 Sectors",
        "🥇 Metals",
        "📈 Buy/Sell",
        "💼 Portfolio Builder"
    ])

    # SENSEX
    with tab1:

        st.subheader("Sensex Performance")

        s_df = yf.download(
            "^BSESN",
            period="1y",
            interval="1d",
            progress=False,
            auto_adjust=True
        )

        if not s_df.empty:

            if isinstance(s_df.columns, pd.MultiIndex):
                s_df.columns = s_df.columns.get_level_values(0)

            fig_s = go.Figure(
                data=[
                    go.Candlestick(
                        x=s_df.index,
                        open=s_df["Open"],
                        high=s_df["High"],
                        low=s_df["Low"],
                        close=s_df["Close"]
                    )
                ]
            )

            fig_s.update_layout(
                template="plotly_dark",
                xaxis_rangeslider_visible=False,
                height=450
            )

            st.plotly_chart(fig_s, use_container_width=True)

        else:
            st.warning("Sensex data unavailable.")

    # TOP 10
    with tab2:

        st.subheader("🏆 Top 10 Multi-Period Performers")

        top10 = df.nlargest(10, "Momentum")

        st.dataframe(
            top10[
                [
                    "Stock", "Sector", "Price",
                    "1M %", "3M %", "6M %",
                    "1Y %", "3Y %", "5Y %",
                    "Momentum", "Trend"
                ]
            ],
            use_container_width=True,
            hide_index=True
        )

    # SCANNER
    with tab3:

        st.subheader(f"Full Market Scanner ({len(df)} stocks)")

        sector_filter = st.multiselect(
            "Filter by sector",
            sorted(df["Sector"].dropna().unique())
        )

        trend_filter = st.multiselect(
            "Filter by trend",
            ["🟢 Up", "🔴 Down"]
        )

        filtered = df.copy()

        if sector_filter:
            filtered = filtered[
                filtered["Sector"].isin(sector_filter)
            ]

        if trend_filter:
            filtered = filtered[
                filtered["Trend"].isin(trend_filter)
            ]

        st.dataframe(
            filtered.sort_values(
                ["Vol", "Momentum"],
                ascending=[False, False]
            ),
            use_container_width=True,
            hide_index=True
        )

        st.download_button(
            "⬇️ Download Scanner CSV",
            filtered.to_csv(index=False),
            file_name="market_scanner.csv",
            mime="text/csv"
        )

    # SECTORS
    with tab4:

        st.subheader("Sector Performance")

        sel_p = st.select_slider(
            "Timeline",
            options=list(PERIODS.keys()),
            value="1Y",
            key="sec_period"
        )

        col = f"{sel_p} %"

        sec_perf = (
            df.groupby("Sector")[col]
            .mean()
            .reset_index()
            .sort_values(by=col, ascending=False)
        )

        fig = px.bar(
            sec_perf,
            x="Sector",
            y=col,
            color=col,
            color_continuous_scale="RdYlGn",
            color_continuous_midpoint=0,
            title=f"Sector Average Return ({sel_p})"
        )

        fig.update_layout(template="plotly_dark")

        st.plotly_chart(fig, use_container_width=True)

        st.markdown("**Sector performance across all timelines**")

        heat = (
            df.groupby("Sector")[
                [f"{p} %" for p in PERIODS]
            ]
            .mean()
            .round(1)
        )

        heat = heat.sort_values(by=col, ascending=False)

        fig_h = px.imshow(
            heat,
            color_continuous_scale="RdYlGn",
            color_continuous_midpoint=0,
            aspect="auto",
            text_auto=True
        )

        fig_h.update_layout(
            template="plotly_dark",
            height=max(350, 28 * len(heat) + 100)
        )

        st.plotly_chart(fig_h, use_container_width=True)

        sel = st.selectbox(
            "Drill Down Sector",
            sec_perf["Sector"].tolist(),
            key="sec_drill"
        )

        if sel:
            st.dataframe(
                df[df["Sector"] == sel].sort_values(
                    by=col,
                    ascending=False
                ),
                use_container_width=True,
                hide_index=True
            )

    # METALS
    with tab5:

        st.subheader("🥇 Metals & Market Momentum")

        metal_data = get_metals("5y")

        if metal_data:

            flow_data = []

            for name, d in metal_data.items():

                rsi = ta.momentum.RSIIndicator(
                    d["Close"],
                    window=14
                ).rsi().iloc[-1]

                status = (
                    "🔴 Overbought" if rsi > 70
                    else "🟢 Oversold" if rsi < 30
                    else "⚪ Neutral"
                )

                row = {
                    "Metal": name,
                    "Price": round(float(d["Close"].iloc[-1]), 2)
                }

                for p, days in PERIODS.items():
                    row[f"{p} %"] = round(
                        float(get_ret(d, days)), 1
                    )

                row.update({
                    "RSI": round(float(rsi), 1),
                    "Momentum Status": status
                })

                flow_data.append(row)

            st.dataframe(
                pd.DataFrame(flow_data),
                use_container_width=True,
                hide_index=True
            )

            m_p = st.select_slider(
                "Chart timeline",
                options=list(PERIODS.keys()),
                value="1Y",
                key="metal_period"
            )

            n = PERIODS[m_p]

            fig_m = go.Figure()

            for name, d in metal_data.items():

                w = d["Close"].tail(n + 1)

                if len(w) > 1:
                    fig_m.add_trace(
                        go.Scatter(
                            x=w.index,
                            y=(w / w.iloc[0]) * 100,
                            mode="lines",
                            name=name
                        )
                    )

            fig_m.update_layout(
                title=f"Metals ({m_p} trend, rebased to 100)",
                template="plotly_dark",
                height=400
            )

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
                    msg += (
                        f"• {r['Stock']} "
                        f"(Score: {r['Momentum']}) "
                        f"₹{r['Price']}\n"
                    )

                success, err = send_telegram_message(
                    tg_token, tg_chat_id, msg
                )

                if success:
                    st.success("Report sent to Telegram.")
                else:
                    st.error(err)

        with col2:

            if st.button("📅 Send Weekly Update"):

                top10 = df.nlargest(10, "1M %")

                msg = "<b>📅 Top 10 Stocks by 1M Return</b>\n\n"

                for _, r in top10.iterrows():
                    msg += (
                        f"• {r['Stock']}: "
                        f"{r['1M %']}% "
                        f"(₹{r['Price']})\n"
                    )

                success, err = send_telegram_message(
                    tg_token, tg_chat_id, msg
                )

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

                    rsi = ta.momentum.RSIIndicator(
                        close,
                        window=14
                    ).rsi().iloc[-1]

                    macd = ta.trend.MACD(close)

                    ml = macd.macd().iloc[-1]
                    ms = macd.macd_signal().iloc[-1]

                    stock_row = df[
                        df["Stock"] == stock
                    ].iloc[0]

                    mom_score = stock_row["Momentum"]

                    if rsi < 40 and ml > ms:

                        typ = "STRONG BUY"
                        hold = (
                            "1-2 Months"
                            if mom_score > 15
                            else "2-3 Weeks"
                        )
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

                    impact = (
                        abs(rsi - 50)
                        + abs(mom_score) * 0.5
                        + (
                            10
                            if stock_row["Vol"] == "🚨 SPIKE"
                            else 0
                        )
                    )

                    sig_list.append({
                        "Stock": stock,
                        "Price": round(float(close.iloc[-1]), 2),
                        "RSI": round(float(rsi), 1),
                        "Type": typ,
                        "Action": f"{SIGNAL_EMOJI[typ]} {typ}",
                        "Hold Time": hold,
                        "Impact": round(float(impact), 1),
                        "Why?": why
                    })

                except Exception:
                    continue

                progress.progress((i + 1) / len(stocks))

            progress.empty()

            if sig_list:

                sig_df = pd.DataFrame(sig_list)

                sig_df["_order"] = sig_df["Type"].map({
                    k: i for i, k in enumerate(SIGNAL_ORDER)
                })

                sig_df = (
                    sig_df.sort_values(
                        ["_order", "Impact"],
                        ascending=[True, False]
                    )
                    .drop(columns=["_order"])
                )

                st.session_state.sig_df = sig_df

                success, err = send_telegram_message(
                    tg_token,
                    tg_chat_id,
                    build_alert_message(sig_list, tg_cap)
                )

                if success:
                    st.success("Buy/Sell alerts sent to Telegram.")
                else:
                    st.error(f"Telegram error: {err}")

            else:
                st.info("No signals generated. Market conditions are neutral.")

        if "sig_df" in st.session_state:

            st.subheader("Generated Signals")

            st.dataframe(
                st.session_state.sig_df,
                use_container_width=True,
                hide_index=True
            )

            st.download_button(
                "⬇️ Download Signals CSV",
                st.session_state.sig_df.to_csv(index=False),
                file_name="buy_sell_signals.csv",
                mime="text/csv"
            )

   
    # --- TAB 7: PORTFOLIO BUILDER ---
    with tab7:
        st.subheader("💼 Portfolio Builder")
        st.caption("I'm not a financial advisor. This is a quantitative allocation model, not a return guarantee.")

        col_in1, col_in2, col_in3 = st.columns(3)

        with col_in1:
            inv_amount = st.number_input(
                "Investment Amount (₹)",
                min_value=1000,
                value=40000,
                step=1000,
                key="pb_amount"
            )

        with col_in2:
            horizon = st.select_slider(
                "Investment Horizon",
                options=["Under 6 months", "6-24 months", "3+ years"],
                value="6-24 months",
                key="pb_horizon"
            )

        with col_in3:
            risk = st.slider(
                "Risk Tolerance (1-10)",
                1, 10, 5,
                key="pb_risk"
            )
            risk_label = (
                "Conservative" if risk <= 3
                else "Balanced" if risk <= 7
                else "Aggressive"
            )
            st.write(f"Profile: **{risk_label}**")

        if st.button("Build Portfolio", key="pb_build_btn"):

            try:
                p_data_local = st.session_state.p_data

                num_pos = int(round(interpolate(risk, 18, 13, 10)))
                max_w = interpolate(risk, 0.07, 0.10, 0.15)
                max_sec_w = interpolate(risk, 0.20, 0.25, 0.35)
                vol_cap = interpolate(risk, 0.25, 0.40, 1.0)
                liq_floor = interpolate(risk, 50, 20, 10)
                stop_mult = interpolate(risk, 3.0, 2.5, 2.0)

                # A ₹40,000 portfolio should not be forced into 10-18 stocks.
                # Use a smaller, practical number of holdings for smaller amounts.
                num_pos = min(
                    num_pos,
                    max(3, int(inv_amount // 3000))
                )

                st.write("### Risk Parameters")
                st.write(
                    f"Target holdings: **{num_pos}** | "
                    f"Maximum stock weight: **{max_w * 100:.1f}%** | "
                    f"Maximum sector weight: **{max_sec_w * 100:.1f}%**"
                )

                # ------------------------------------------
                # STOCK SCORING AND ELIGIBILITY
                # ------------------------------------------
                eligible = []

                for _, market_row in df.iterrows():

                    sym = market_row["Stock"]
                    df_p = p_data_local.get(sym)

                    if df_p is None or len(df_p) < 252:
                        continue

                    try:
                        close = df_p["Close"].astype(float)
                        high = df_p["High"].astype(float)
                        low = df_p["Low"].astype(float)
                        volume = df_p["Volume"].astype(float)

                        price = float(close.iloc[-1])

                        if not np.isfinite(price) or price <= 0:
                            continue

                        daily_returns = close.pct_change().dropna()
                        vol_1y = float(
                            daily_returns.tail(252).std() * np.sqrt(252)
                        )

                        if not np.isfinite(vol_1y) or vol_1y <= 0:
                            continue

                        liq_cr = float(
                            (close * volume).tail(20).mean() / 10000000
                        )

                        above_200 = (
                            market_row["Long Trend"] == "🟢 Bullish"
                        )

                        rsi = float(
                            ta.momentum.RSIIndicator(
                                close, window=14
                            ).rsi().iloc[-1]
                        )

                        ret_3m = float(market_row["3M %"])
                        ret_6m = float(market_row["6M %"])
                        ret_1y = float(market_row["1Y %"])
                        ret_3y = float(market_row["3Y %"])
                        ret_5y = float(market_row["5Y %"])
                        momentum = float(market_row["Momentum"])

                        # Gradually relax filters if a stock fails.
                        pass_vol = vol_1y <= vol_cap
                        pass_liq = liq_cr >= liq_floor
                        pass_rs = ret_3m > 0
                        pass_trend = above_200

                        if not pass_vol:
                            pass_vol = vol_1y <= vol_cap + 0.15

                        if not pass_liq:
                            pass_liq = liq_cr >= liq_floor / 2

                        if not pass_rs:
                            pass_rs = True

                        if not pass_trend:
                            pass_trend = True

                        if not (
                            pass_vol and pass_liq
                            and pass_rs and pass_trend
                        ):
                            continue

                        if horizon == "Under 6 months":
                            pullback = (
                                1 if 30 <= rsi <= 50 and above_200 else 0
                            )
                            score = (
                                0.40 * pullback
                                + 0.30 * (ret_3m / 100)
                                + 0.30 * (
                                    1 if market_row["Trend"] == "🟢 Up"
                                    else 0
                                )
                            )

                        elif horizon == "6-24 months":
                            score = (
                                0.50 * (momentum / 100)
                                + 0.25 * (ret_6m / 100)
                                + 0.25 * (
                                    1 if market_row["Trend"] == "🟢 Up"
                                    else 0
                                )
                            )

                        else:
                            consistency = (
                                (1 if ret_1y > 0 else 0)
                                + (1 if ret_3y > 0 else 0)
                                + (1 if ret_5y > 0 else 0)
                            )

                            max_dd = calc_max_drawdown(
                                daily_returns.tail(756)
                            )

                            score = (
                                0.35 * (consistency / 3)
                                + 0.35 * (1 - abs(max_dd))
                                + 0.30 * (1 - min(vol_1y, 1))
                            )

                        low_vol_score = 1 - min(vol_1y, 1)
                        vol_weight = ((10 - risk) / 10) * 0.4

                        score = (
                            score * (1 - vol_weight)
                            + low_vol_score * vol_weight
                        )

                        if risk >= 8:
                            score += (momentum / 100) * 0.2

                        atr = float(
                            ta.volatility.AverageTrueRange(
                                high, low, close, window=14
                            ).average_true_range().iloc[-1]
                        )

                        if not np.isfinite(atr) or atr <= 0:
                            continue

                        # IMPORTANT:
                        # Carry every column needed by the final display.
                        eligible.append({
                            "Stock": sym,
                            "Sector": market_row["Sector"],
                            "Price": price,
                            "Momentum": momentum,
                            "3M %": ret_3m,
                            "6M %": ret_6m,
                            "1Y %": ret_1y,
                            "3Y %": ret_3y,
                            "5Y %": ret_5y,
                            "Score": float(score),
                            "Vol": vol_1y,
                            "Liq": liq_cr,
                            "RSI": rsi,
                            "ATR": atr
                        })

                    except Exception:
                        continue

                df_elig = pd.DataFrame(eligible)

                if df_elig.empty:
                    st.error(
                        "No stocks passed the data and eligibility checks. "
                        "Run the market scanner again and retry."
                    )
                    st.stop()

                df_elig = (
                    df_elig.replace([np.inf, -np.inf], np.nan)
                    .dropna(subset=["Score", "Price", "Vol"])
                    .sort_values("Score", ascending=False)
                )

                if df_elig.empty:
                    st.error("No valid stocks available for allocation.")
                    st.stop()

                # ------------------------------------------
                # SELECT STOCKS WITH SECTOR DIVERSIFICATION
                # ------------------------------------------
                selected = []
                sector_counts = {}

                sector_limit = max(
                    1,
                    int(math.ceil(max_sec_w * num_pos))
                )

                for _, candidate in df_elig.iterrows():

                    sector = candidate["Sector"]

                    if sector_counts.get(sector, 0) < sector_limit:
                        selected.append(candidate)
                        sector_counts[sector] = (
                            sector_counts.get(sector, 0) + 1
                        )

                    if len(selected) >= num_pos:
                        break

                # If sector limits leave positions unfilled,
                # fill them with the next highest-scoring stocks.
                selected_symbols = {
                    item["Stock"] for item in selected
                }

                if len(selected) < num_pos:
                    for _, candidate in df_elig.iterrows():
                        if candidate["Stock"] in selected_symbols:
                            continue

                        selected.append(candidate)
                        selected_symbols.add(candidate["Stock"])

                        if len(selected) >= num_pos:
                            break

                df_sel = pd.DataFrame(selected).reset_index(drop=True)

                if df_sel.empty:
                    st.error("Portfolio selection returned no stocks.")
                    st.stop()

                # ------------------------------------------
                # WEIGHTING
                # ------------------------------------------
                # Inverse-volatility allocation.
                inv_vol = 1 / df_sel["Vol"].clip(lower=0.01)
                raw_weights = inv_vol / inv_vol.sum()

                # Ensure the maximum weight does not make
                # a fully invested portfolio mathematically impossible.
                effective_max_w = max(
                    max_w,
                    1 / len(df_sel)
                )

                df_sel["Weight"] = cap_weights(
                    raw_weights.tolist(),
                    effective_max_w
                )

                # Normalize against floating-point rounding.
                df_sel["Weight"] = (
                    df_sel["Weight"] / df_sel["Weight"].sum()
                )

                # ------------------------------------------
                # DEPLOY THE FULL AVAILABLE AMOUNT
                # ------------------------------------------
                # No intentional cash buffer, ETF sleeve or gold sleeve.
                df_sel["Target Amount"] = (
                    df_sel["Weight"] * float(inv_amount)
                )

                df_sel["Shares"] = np.floor(
                    df_sel["Target Amount"] / df_sel["Price"]
                ).astype(int)

                df_sel["Invested"] = (
                    df_sel["Shares"] * df_sel["Price"]
                )

                # Distribute remaining money into additional shares.
                # Prioritize stocks furthest below their target allocation.
                remaining = round(
                    float(inv_amount) - df_sel["Invested"].sum(), 2
                )

                max_iterations = 10000
                iteration = 0

                while remaining > 0 and iteration < max_iterations:

                    iteration += 1

                    df_sel["Remaining Target"] = (
                        df_sel["Target Amount"] - df_sel["Invested"]
                    )

                    affordable = df_sel[
                        df_sel["Price"] <= remaining
                    ].copy()

                    if affordable.empty:
                        break

                    affordable = affordable.sort_values(
                        "Remaining Target",
                        ascending=False
                    )

                    bought = False

                    for idx in affordable.index:

                        share_price = float(df_sel.loc[idx, "Price"])

                        if share_price <= remaining:
                            df_sel.loc[idx, "Shares"] += 1
                            df_sel.loc[idx, "Invested"] += share_price
                            remaining = round(
                                remaining - share_price, 2
                            )
                            bought = True
                            break

                    if not bought:
                        break

                df_sel["Stop"] = (
                    df_sel["Price"] - stop_mult * df_sel["ATR"]
                )

                total_invested = float(df_sel["Invested"].sum())
                uninvested = round(
                    float(inv_amount) - total_invested, 2
                )

                actual_weight_total = (
                    total_invested / inv_amount
                    if inv_amount > 0 else 0
                )

                # ------------------------------------------
                # PORTFOLIO SUMMARY
                # ------------------------------------------
                st.write("### Portfolio Summary")

                c1, c2, c3, c4 = st.columns(4)

                c1.metric(
                    "Investment Budget",
                    f"₹{inv_amount:,.0f}"
                )

                c2.metric(
                    "Actually Invested",
                    f"₹{total_invested:,.2f}"
                )

                c3.metric(
                    "Amount Remaining",
                    f"₹{uninvested:,.2f}"
                )

                c4.metric(
                    "Capital Deployed",
                    f"{actual_weight_total * 100:.2f}%"
                )

                if uninvested > 0:
                    st.warning(
                        f"₹{uninvested:,.2f} could not buy another whole "
                        "share at the current prices. This is a share-unit "
                        "constraint, not an intentional cash reserve."
                    )
                else:
                    st.success("100% of the investment budget is deployed.")

                fig_pie = px.pie(
                    df_sel[df_sel["Invested"] > 0],
                    values="Invested",
                    names="Stock",
                    hole=0.45,
                    title="Actual Portfolio Allocation"
                )

                fig_pie.update_layout(template="plotly_dark")
                st.plotly_chart(fig_pie, use_container_width=True)

                # ------------------------------------------
                # PORTFOLIO HOLDINGS
                # ------------------------------------------
                st.write("### Recommended Holdings")

                df_display = df_sel[
                    [
                        "Stock", "Sector", "Price",
                        "Weight", "Shares", "Invested",
                        "Stop", "Momentum", "3M %",
                        "RSI", "Score"
                    ]
                ].copy()

                df_display["Weight"] = (
                    df_display["Invested"] / inv_amount * 100
                ).round(2).astype(str) + "%"

                for col in [
                    "Price", "Invested", "Stop",
                    "Momentum", "3M %", "RSI", "Score"
                ]:
                    df_display[col] = df_display[col].round(2)

                st.dataframe(
                    df_display,
                    hide_index=True,
                    use_container_width=True
                )

                st.download_button(
                    "⬇️ Download Portfolio CSV",
                    df_display.to_csv(index=False),
                    file_name="khaata_portfolio.csv",
                    mime="text/csv"
                )

                # ------------------------------------------
                # HISTORICAL RISK CHECK
                # ------------------------------------------
                st.write("### Reality Check — Historical Risk")

                try:
                    nifty_df = yf.download(
                        "^NSEI",
                        period="5y",
                        interval="1d",
                        progress=False,
                        auto_adjust=True
                    )

                    if isinstance(nifty_df.columns, pd.MultiIndex):
                        nifty_df.columns = nifty_df.columns.get_level_values(0)

                    nifty_close = (
                        nifty_df["Close"].squeeze().dropna()
                    )

                    selected_closes = {}

                    for _, holding in df_sel.iterrows():
                        stock_data = p_data_local.get(holding["Stock"])

                        if stock_data is not None:
                            selected_closes[holding["Stock"]] = (
                                stock_data["Close"]
                            )

                    p_closes = pd.DataFrame(selected_closes).dropna()

                    if (
                        len(p_closes) > 63
                        and len(nifty_close) > 63
                    ):

                        weights = (
                            df_sel.set_index("Stock")["Weight"]
                        )

                        portfolio_returns = (
                            p_closes.pct_change()
                            .mul(weights, axis=1)
                            .sum(axis=1)
                            .dropna()
                        )

                        common = pd.concat(
                            [
                                portfolio_returns.rename("Portfolio"),
                                nifty_close.pct_change().rename("Nifty")
                            ],
                            axis=1,
                            join="inner"
                        ).dropna()

                        if len(common) > 63:

                            p_rets = common["Portfolio"]
                            n_rets = common["Nifty"]

                            cumulative = (1 + p_rets).cumprod()

                            roll_1m = (
                                cumulative / cumulative.shift(21) - 1
                            ).min()

                            roll_3m = (
                                cumulative / cumulative.shift(63) - 1
                            ).min()

                            max_dd = calc_max_drawdown(p_rets)
                            ann_vol = p_rets.std() * np.sqrt(252)

                            nifty_variance = n_rets.var()

                            beta = (
                                np.cov(p_rets, n_rets)[0, 1]
                                / nifty_variance
                                if nifty_variance > 0 else np.nan
                            )

                            r1, r2, r3, r4, r5 = st.columns(5)

                            r1.metric(
                                "Worst 1M",
                                f"{roll_1m * 100:.1f}%",
                                f"₹{roll_1m * total_invested:,.0f}"
                            )

                            r2.metric(
                                "Worst 3M",
                                f"{roll_3m * 100:.1f}%",
                                f"₹{roll_3m * total_invested:,.0f}"
                            )

                            r3.metric(
                                "Max Drawdown",
                                f"{max_dd * 100:.1f}%",
                                f"₹{max_dd * total_invested:,.0f}"
                            )

                            r4.metric(
                                "Annualised Volatility",
                                f"{ann_vol * 100:.1f}%"
                            )

                            r5.metric(
                                "Beta vs Nifty",
                                f"{beta:.2f}" if np.isfinite(beta) else "N/A"
                            )

                            st.caption(
                                "Historical risk of today's selected stocks. "
                                "This is not a return forecast and may contain "
                                "look-ahead and survivorship bias."
                            )

                        else:
                            st.info(
                                "Not enough overlapping historical data "
                                "to calculate portfolio risk."
                            )

                    else:
                        st.info(
                            "Insufficient historical data for the risk check."
                        )

                except Exception as e:
                    st.warning(
                        f"Could not calculate historical risk: {e}"
                    )

                # ------------------------------------------
                # TELEGRAM
                # ------------------------------------------
                if st.button(
                    "📤 Send Portfolio Plan to Telegram",
                    key="pb_telegram"
                ):

                    msg = (
                        f"<b>💼 Khaata Portfolio Plan</b>\n"
                        f"Budget: ₹{inv_amount:,.0f}\n"
                        f"Invested: ₹{total_invested:,.2f}\n"
                        f"Remaining: ₹{uninvested:,.2f}\n"
                        f"Risk: {risk}/10\n"
                        f"Horizon: {horizon}\n\n"
                    )

                    for _, holding in df_sel.iterrows():
                        if holding["Shares"] > 0:
                            msg += (
                                f"• <b>{holding['Stock']}</b>: "
                                f"{holding['Shares']} shares "
                                f"@ ₹{holding['Price']:.2f} "
                                f"(Invested ₹{holding['Invested']:.2f}, "
                                f"Stop ₹{holding['Stop']:.2f})\n"
                            )

                    success, err = send_telegram_message(
                        tg_token,
                        tg_chat_id,
                        msg
                    )

                    if success:
                        st.success("Portfolio plan sent to Telegram.")
                    else:
                        st.error(f"Telegram error: {err}")

            except Exception as e:
                st.error(f"❌ Failed to build portfolio: {e}")

