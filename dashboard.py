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
        st.caption("Not investment advice. This is a quantitative allocation tool.")
        
        col_in1, col_in2, col_in3 = st.columns(3)
        with col_in1:
            inv_amount = st.number_input("Investment Amount (₹)", min_value=25000, value=500000, step=25000, key="pb_amount")
        with col_in2:
            horizon = st.select_slider("Horizon", options=["Under 6 months", "6-24 months", "3+ years"], value="6-24 months", key="pb_horizon")
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
                
                if risk <= 3: core_pct = 0.50
                elif risk <= 7: core_pct = 0.25
                else: core_pct = interpolate(risk, 0, 0.10, 0)
                
                # FIXED: Gold trend error using .squeeze() to prevent Series ambiguity
                gold_pct = 0.0
                try:
                    gold_df = yf.download("GC=F", period="1y", interval="1d", progress=False)
                    if not gold_df.empty:
                        if isinstance(gold_df.columns, pd.MultiIndex): gold_df.columns = gold_df.columns.get_level_values(0)
                        if len(gold_df) >= 200:
                            gold_close = gold_df['Close'].squeeze()
                            gold_sma = gold_close.rolling(200).mean().iloc[-1]
                            gold_trend_up = bool(gold_close.iloc[-1] > gold_sma)
                            if gold_trend_up and risk <= 5: gold_pct = 0.10
                except: pass
                
                st.write("**Risk Parameters Applied:**")
                st.dataframe(pd.DataFrame([{
                    "Positions": num_pos, "Max Stock %": f"{max_w*100:.1f}%", "Max Sector %": f"{max_sec_w*100:.1f}%",
                    "Vol Cap": "None" if vol_cap >= 1.0 else f"{vol_cap*100:.0f}%", "Liq Floor (₹Cr)": f"{liq_floor:.0f}",
                    "Stop Mult": f"{stop_mult:.1f}x ATR", "Cash Buffer": f"{cash_buffer*100:.0f}%", 
                    "Core ETF": f"{core_pct*100:.0f}%", "Gold Sleeve": f"{gold_pct*100:.0f}%"
                })]), hide_index=True)

                # Scoring
                eligible = []
                p_data_local = st.session_state.p_data
                
                for _, row in df.iterrows():
                    sym = row['Stock']
                    df_p = p_data_local.get(sym)
                    if df_p is None or len(df_p) < 252: continue
                    
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
                        if not relax_a: relax_a = True
                        elif not relax_b: relax_b = True
                        elif not relax_c: relax_c = True
                        elif not relax_d: relax_d = True
                        else: break
                        
                    if pass_vol and pass_liq and pass_rs and pass_above200:
                        score = 0
                        rsi = ta.momentum.RSIIndicator(df_p['Close'], window=14).rsi().iloc[-1]
                        
                        if horizon == "Under 6 months":
                            pullback = 1 if 30 <= rsi <= 50 and above_200 else 0
                            score = (0.4 * pullback) + (0.3 * (row['3M %'] / 100)) + (0.3 * (1 if row['Trend'] == "🟢 Up" else 0))
                        elif horizon == "6-24 months":
                            score = (0.5 * (row['Momentum'] / 100)) + (0.25 * (row['6M %'] / 100)) + (0.25 * (1 if row['Trend'] == "🟢 Up" else 0))
                        else:
                            consistency = (1 if row['1Y %'] > 0 else 0) + (1 if row['3Y %'] > 0 else 0) + (1 if row['5Y %'] > 0 else 0)
                            max_dd = calc_max_drawdown(df_p['Close'].pct_change().tail(756))
                            score = (0.35 * (consistency/3)) + (0.35 * (1 - abs(max_dd))) + (0.30 * (1 - vol_1y))
                            
                        low_vol_score = 1 - vol_1y
                        vol_weight = ((10 - risk) / 10) * 0.4
                        score = (score * (1 - vol_weight)) + (low_vol_score * vol_weight)
                        if risk >= 8: score += (row['Momentum'] / 100) * 0.2
                        
                        eligible.append({
                            "Stock": sym, "Sector": row['Sector'], "Price": row['Price'], "Score": score,
                            "Vol": vol_1y, "Liq": liq_cr, "RSI": rsi, "RS_3M": row['3M %'],
                            "ATR": ta.volatility.AverageTrueRange(df_p['High'], df_p['Low'], df_p['Close']).average_true_range().iloc[-1]
                        })
                
                if len(eligible) < 10:
                    st.warning("Not enough stocks passed the strict filters. Relaxed filters applied to guarantee at least 10 stocks.")
                
                df_elig = pd.DataFrame(eligible).sort_values(by="Score", ascending=False)
                
                # Construction
                selected = []
                sector_counts = {}
                for _, row in df_elig.iterrows():
                    sec = row['Sector']
                    if sector_counts.get(sec, 0) < math.floor(max_sec_w * num_pos):
                        selected.append(row)
                        sector_counts[sec] = sector_counts.get(sec, 0) + 1
                    if len(selected) >= num_pos: break
                
                df_sel = pd.DataFrame(selected)
                df_sel['InvVol'] = 1 / df_sel['Vol']
                df_sel['Weight'] = df_sel['InvVol'] / df_sel['InvVol'].sum()
                df_sel['Weight'] = cap_weights(df_sel['Weight'].tolist(), max_w)
                
                breadth = (df['Long Trend'] == "🟢 Bullish").sum() / len(df) * 100
                if breadth < 40: cash_buffer += 0.20
                if breadth < 25: cash_buffer += 0.40
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
                col_s3.metric("Core + Gold + Cash", f"₹{core_amt + gold_amt + cash_amt:,.0f}")
                
                fig_pie = px.pie(values=[df_sel['Invested'].sum(), core_amt, gold_amt, cash_amt], 
                                 names=['Equity', 'Core ETF', 'Gold', 'Cash'], hole=0.5)
                st.plotly_chart(fig_pie, use_container_width=True)
                
                st.write("### Reality Check (Historical Risk)")
                try:
                    nifty_df = yf.download("^NSEI", period="5y", interval="1d", progress=False)
                    if isinstance(nifty_df.columns, pd.MultiIndex): nifty_df.columns = nifty_df.columns.get_level_values(0)
                    nifty_close = nifty_df['Close'].squeeze().dropna()

                    p_closes = pd.DataFrame({row['Stock']: p_data_local[row['Stock']]['Close'] for _, row in df_sel.iterrows()}).dropna()
                    p_rets = (p_closes.pct_change() * df_sel.set_index('Stock')['Weight']).sum(axis=1).dropna()
                    
                    nifty_rets = nifty_close.pct_change().tail(len(p_rets)).dropna()
                    p_rets = p_rets.tail(len(nifty_rets))
                    
                    cum_ret = (1 + p_rets).cumprod()
                    roll_1m = (cum_ret / cum_ret.shift(21) - 1).min()
                    roll_3m = (cum_ret / cum_ret.shift(63) - 1).min()
                    max_dd = calc_max_drawdown(p_rets)
                    ann_vol = p_rets.std() * np.sqrt(252)
                    beta = np.cov(p_rets, nifty_rets)[0,1] / np.var(nifty_rets)
                    
                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("Worst 1M", f"{roll_1m*100:.1f}%", f"₹{roll_1m*equity_amt:,.0f}")
                    c2.metric("Worst 3M", f"{roll_3m*100:.1f}%", f"₹{roll_3m*equity_amt:,.0f}")
                    c3.metric("Max Drawdown", f"{max_dd*100:.1f}%", f"₹{max_dd*equity_amt:,.0f}")
                    c4.metric("Ann. Volatility", f"{ann_vol*100:.1f}%")
                    c5.metric("Beta", f"{beta:.2f}")
                    st.caption("Historical risk of today's picks. NOT a return forecast (look-ahead bias).")
                except Exception as e:
                    st.warning(f"Could not compute backtest: {e}")

                df_display = df_sel[['Stock', 'Sector', 'Price', 'Weight', 'Shares', 'Invested', 'Stop', 'Momentum', '3M %', 'RSI']].copy()
                df_display['Weight'] = df_display['Weight'].apply(lambda x: f"{x*100:.1f}%")
                df_display['Stop'] = df_display['Stop'].round(1)
                st.dataframe(df_display, hide_index=True, use_container_width=True)
                
                if st.button("📤 Send Plan to Telegram"):
                    msg = f"<b>💼 Portfolio Plan (₹{inv_amount:,.0f})</b>\nRisk: {risk}\n\n"
                    for _, r in df_sel.iterrows():
                        msg += f"• <b>{r['Stock']}</b>: {r['Shares']} sh @ ₹{r['Price']} (Stop: ₹{r['Stop']:.1f})\n"
                    success, err = send_telegram_message(tg_token, tg_chat_id, msg)
                    if success: st.success("✅ Sent to Telegram!")
                    else: st.error(f"❌ Error: {err}")

            except Exception as e:
                st.error(f"❌ Failed to build portfolio: {e}")

else:

    st.info(
        "Click the button above to download market data and build your scanner."
    )
