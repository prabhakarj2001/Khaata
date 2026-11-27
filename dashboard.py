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
# MARKET DRIVERS & TIMESTAMP
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
            response = requests.post(url, json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}, timeout=15)
            result = response.json()
            if not result.get("ok"):
                return False, result.get("description", "Telegram error")
        return True, "Sent successfully"
    except Exception as e:
        return False, str(e)

SIGNAL_ORDER = ["STRONG SELL", "STRONG BUY", "WEAK SELL", "WEAK BUY"]
SIGNAL_EMOJI = {"STRONG SELL": "🔴", "STRONG BUY": "🟢", "WEAK SELL": "🟠", "WEAK BUY": "🟡"}

def allocate_alerts(sig_list, cap):
    groups = {k: sorted([s for s in sig_list if s["Type"] == k], key=lambda x: x["Impact"], reverse=True) for k in SIGNAL_ORDER}
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
            if remaining == 0: break
    return picked, groups

def build_alert_message(sig_list, cap):
    picked, groups = allocate_alerts(sig_list, cap)
    shown = sum(len(v) for v in picked.values())
    msg = f"<b>🚨 Buy/Sell Alerts</b> ({shown} of {len(sig_list)} shown)\n"
    for k in SIGNAL_ORDER:
        if not picked[k]: continue
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
    if len(df) <= 1: return 0.0
    actual_days = min(days, len(df) - 1)
    old_price = df["Close"].iloc[-(actual_days + 1)]
    current_price = df["Close"].iloc[-1]
    if pd.isna(old_price) or old_price == 0: return 0.0
    return ((current_price - old_price) / old_price) * 100

@st.cache_data(ttl=3600)
def download_data(symbols, period="5y"):
    all_data = {}
    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i + 50]
        tickers = [s if s.endswith(".NS") else s + ".NS" for s in chunk]
        try:
            data = yf.download(tickers, period=period, interval="1d", group_by="ticker", progress=False, threads=True, auto_adjust=True)
            if data.empty: continue
            for orig_sym, clean_sym in zip(chunk, tickers):
                if isinstance(data.columns, pd.MultiIndex) and clean_sym in data.columns.get_level_values(0):
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
            d = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
            if d.empty: continue
            if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
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
        if df_stock is None or len(df_stock) < min_history: continue
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
            volume_ratio = (current_volume / avg_volume if pd.notna(avg_volume) and avg_volume > 0 else 0)
            volume_status = "🚨 SPIKE" if volume_ratio >= 2 else "Normal"
            
            row = {
                "Stock": sym, "Sector": nse_map.get(sym, "Unknown"), "Price": round(price, 2),
                "Momentum": round(float(momentum), 1), "Trend": trend, "Long Trend": long_trend,
                "Volume": round(float(volume_ratio), 2), "Vol": volume_status
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

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab_hot = st.tabs([
        "📉 Sensex", "🏆 Top 10", "📊 Scanner", "🏢 Sectors", 
        "🥇 Metals", "📈 Buy/Sell", "💼 Portfolio Builder", "🔥 Hot Themes"
    ])

    with tab1:
        st.subheader("Sensex Performance")
        s_df = yf.download("^BSESN", period="1y", interval="1d", progress=False, auto_adjust=True)
        if not s_df.empty:
            if isinstance(s_df.columns, pd.MultiIndex): s_df.columns = s_df.columns.get_level_values(0)
            fig_s = go.Figure(data=[go.Candlestick(x=s_df.index, open=s_df["Open"], high=s_df["High"], low=s_df["Low"], close=s_df["Close"])])
            fig_s.update_layout(template="plotly_dark", xaxis_rangeslider_visible=False, height=450)
            st.plotly_chart(fig_s, use_container_width=True)
        else:
            st.warning("Sensex data unavailable.")

    with tab2:
        st.subheader("🏆 Top 10 Multi-Period Performers")
        top10 = df.nlargest(10, "Momentum")
        st.dataframe(top10[["Stock", "Sector", "Price", "1M %", "3M %", "6M %", "1Y %", "3Y %", "5Y %", "Momentum", "Trend"]], use_container_width=True, hide_index=True)

    with tab3:
        st.subheader(f"Full Market Scanner ({len(df)} stocks)")
        sector_filter = st.multiselect("Filter by sector", sorted(df["Sector"].dropna().unique()))
        trend_filter = st.multiselect("Filter by trend", ["🟢 Up", "🔴 Down"])
        filtered = df.copy()
        if sector_filter: filtered = filtered[filtered["Sector"].isin(sector_filter)]
        if trend_filter: filtered = filtered[filtered["Trend"].isin(trend_filter)]
        st.dataframe(filtered.sort_values(["Vol", "Momentum"], ascending=[False, False]), use_container_width=True, hide_index=True)
        st.download_button("⬇️ Download Scanner CSV", filtered.to_csv(index=False), file_name="market_scanner.csv", mime="text/csv")

    with tab4:
        st.subheader("Sector Performance")
        sel_p = st.select_slider("Timeline", options=list(PERIODS.keys()), value="1Y", key="sec_period")
        col = f"{sel_p} %"
        sec_perf = df.groupby("Sector")[col].mean().reset_index().sort_values(by=col, ascending=False)
        fig = px.bar(sec_perf, x="Sector", y=col, color=col, color_continuous_scale="RdYlGn", color_continuous_midpoint=0, title=f"Sector Average Return ({sel_p})")
        fig.update_layout(template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
        sel = st.selectbox("Drill Down Sector", sec_perf["Sector"].tolist(), key="sec_drill")
        if sel: st.dataframe(df[df["Sector"] == sel].sort_values(by=col, ascending=False), use_container_width=True, hide_index=True)

    with tab5:
        st.subheader("🥇 Metals & Market Momentum")
        metal_data = get_metals("5y")
        if metal_data:
            flow_data = []
            for name, d in metal_data.items():
                rsi = ta.momentum.RSIIndicator(d["Close"], window=14).rsi().iloc[-1]
                status = "🔴 Overbought" if rsi > 70 else "🟢 Oversold" if rsi < 30 else "⚪ Neutral"
                row = {"Metal": name, "Price": round(float(d["Close"].iloc[-1]), 2)}
                for p, days in PERIODS.items():
                    row[f"{p} %"] = round(float(get_ret(d, days)), 1)
                row.update({"RSI": round(float(rsi), 1), "Momentum Status": status})
                flow_data.append(row)
            st.dataframe(pd.DataFrame(flow_data), use_container_width=True, hide_index=True)
            m_p = st.select_slider("Chart timeline", options=list(PERIODS.keys()), value="1Y", key="metal_period")
            n = PERIODS[m_p]
            fig_m = go.Figure()
            for name, d in metal_data.items():
                w = d["Close"].tail(n + 1)
                if len(w) > 1: fig_m.add_trace(go.Scatter(x=w.index, y=(w / w.iloc[0]) * 100, mode="lines", name=name))
            fig_m.update_layout(title=f"Metals ({m_p} trend, rebased to 100)", template="plotly_dark", height=400)
            st.plotly_chart(fig_m, use_container_width=True)
        else:
            st.warning("Metals data unavailable.")

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
                if success: st.success("Report sent to Telegram.")
                else: st.error(err)
        with col2:
            if st.button("📅 Send Weekly Update"):
                top10 = df.nlargest(10, "1M %")
                msg = "<b>📅 Top 10 Stocks by 1M Return</b>\n\n"
                for _, r in top10.iterrows():
                    msg += f"• {r['Stock']}: {r['1M %']}% (₹{r['Price']})\n"
                success, err = send_telegram_message(tg_token, tg_chat_id, msg)
                if success: st.success("Weekly report sent.")
                else: st.error(err)

        st.markdown("---")
        if st.button("🔄 Generate Buy/Sell Alerts"):
            sig_list = []
            p_data = st.session_state.p_data
            progress = st.progress(0)
            stocks = df["Stock"].tolist()
            for i, stock in enumerate(stocks):
                df_h = p_data.get(stock)
                if df_h is None or len(df_h) < 30: continue
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

                    impact = abs(rsi - 50) + abs(mom_score) * 0.5 + (10 if stock_row["Vol"] == "🚨 SPIKE" else 0)
                    sig_list.append({
                        "Stock": stock, "Price": round(float(close.iloc[-1]), 2), "RSI": round(float(rsi), 1),
                        "Type": typ, "Action": f"{SIGNAL_EMOJI[typ]} {typ}", "Hold Time": hold,
                        "Impact": round(float(impact), 1), "Why?": why
                    })
                except Exception: continue
                progress.progress((i + 1) / len(stocks))
            progress.empty()

            if sig_list:
                sig_df = pd.DataFrame(sig_list)
                sig_df["_order"] = sig_df["Type"].map({k: i for i, k in enumerate(SIGNAL_ORDER)})
                sig_df = sig_df.sort_values(["_order", "Impact"], ascending=[True, False]).drop(columns=["_order"])
                st.session_state.sig_df = sig_df
                success, err = send_telegram_message(tg_token, tg_chat_id, build_alert_message(sig_list, tg_cap))
                if success: st.success("Buy/Sell alerts sent to Telegram.")
                else: st.error(f"Telegram error: {err}")
            else:
                st.info("No signals generated. Market conditions are neutral.")

        if "sig_df" in st.session_state:
            st.subheader("Generated Signals")
            st.dataframe(st.session_state.sig_df, use_container_width=True, hide_index=True)
            st.download_button("⬇️ Download Signals CSV", st.session_state.sig_df.to_csv(index=False), file_name="buy_sell_signals.csv", mime="text/csv")

    # --- TAB 7: PORTFOLIO BUILDER ---
    with tab7:
        st.subheader("💼 Portfolio Builder")
        st.caption("I'm not a financial advisor. This is a quantitative allocation model, not a return guarantee.")

        col_in1, col_in2, col_in3 = st.columns(3)
        with col_in1:
            inv_amount = st.number_input("Investment Amount (₹)", min_value=1000, value=40000, step=1000, key="pb_amount")
        with col_in2:
            horizon = st.select_slider("Investment Horizon", options=["Under 6 months", "6-24 months", "3+ years"], value="6-24 months", key="pb_horizon")
        with col_in3:
            risk = st.slider("Risk Tolerance (1-10)", 1, 10, 5, key="pb_risk")
            risk_label = "Conservative" if risk <= 3 else "Balanced" if risk <= 7 else "Aggressive"
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

                # Adjust number of stocks based on investment amount (min 3 stocks)
                num_pos = min(num_pos, max(3, int(inv_amount // 3000)))

                st.write("### Risk Parameters")
                st.write(f"Target holdings: **{num_pos}** | Maximum stock weight: **{max_w * 100:.1f}%** | Maximum sector weight: **{max_sec_w * 100:.1f}%**")

                eligible = []
                for _, market_row in df.iterrows():
                    sym = market_row["Stock"]
                    df_p = p_data_local.get(sym)
                    if df_p is None or len(df_p) < 252: continue

                    try:
                        close = df_p["Close"].astype(float)
                        high = df_p["High"].astype(float)
                        low = df_p["Low"].astype(float)
                        volume = df_p["Volume"].astype(float)
                        price = float(close.iloc[-1])
                        if not np.isfinite(price) or price <= 0: continue

                        daily_returns = close.pct_change().dropna()
                        vol_1y = float(daily_returns.tail(252).std() * np.sqrt(252))
                        if not np.isfinite(vol_1y) or vol_1y <= 0: continue

                        liq_cr = float((close * volume).tail(20).mean() / 10000000)
                        above_200 = (market_row["Long Trend"] == "🟢 Bullish")
                        rsi = float(ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1])

                        ret_3m = float(market_row["3M %"])
                        ret_6m = float(market_row["6M %"])
                        ret_1y = float(market_row["1Y %"])
                        ret_3y = float(market_row["3Y %"])
                        ret_5y = float(market_row["5Y %"])
                        momentum = float(market_row["Momentum"])

                        pass_vol = vol_1y <= vol_cap or vol_1y <= (vol_cap + 0.15)
                        pass_liq = liq_cr >= liq_floor or liq_cr >= (liq_floor / 2)
                        pass_rs = ret_3m > 0
                        pass_trend = above_200

                        if not (pass_vol and pass_liq and pass_rs and pass_trend): continue

                        if horizon == "Under 6 months":
                            pullback = 1 if 30 <= rsi <= 50 and above_200 else 0
                            score = (0.40 * pullback + 0.30 * (ret_3m / 100) + 0.30 * (1 if market_row["Trend"] == "🟢 Up" else 0))
                        elif horizon == "6-24 months":
                            score = (0.50 * (momentum / 100) + 0.25 * (ret_6m / 100) + 0.25 * (1 if market_row["Trend"] == "🟢 Up" else 0))
                        else:
                            consistency = (1 if ret_1y > 0 else 0) + (1 if ret_3y > 0 else 0) + (1 if ret_5y > 0 else 0)
                            max_dd = calc_max_drawdown(daily_returns.tail(756))
                            score = (0.35 * (consistency / 3) + 0.35 * (1 - abs(max_dd)) + 0.30 * (1 - min(vol_1y, 1)))

                        low_vol_score = 1 - min(vol_1y, 1)
                        vol_weight = ((10 - risk) / 10) * 0.4
                        score = (score * (1 - vol_weight) + low_vol_score * vol_weight)
                        if risk >= 8: score += (momentum / 100) * 0.2

                        atr = float(ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range().iloc[-1])
                        if not np.isfinite(atr) or atr <= 0: continue

                        eligible.append({
                            "Stock": sym, "Sector": market_row["Sector"], "Price": price,
                            "Momentum": momentum, "3M %": ret_3m, "6M %": ret_6m, "1Y %": ret_1y,
                            "3Y %": ret_3y, "5Y %": ret_5y, "Score": float(score),
                            "Vol": vol_1y, "Liq": liq_cr, "RSI": rsi, "ATR": atr
                        })
                    except Exception: continue

                df_elig = pd.DataFrame(eligible)
                if df_elig.empty:
                    st.error("No stocks passed the data checks. Run the market scanner again.")
                    st.stop()

                df_elig = df_elig.replace([np.inf, -np.inf], np.nan).dropna(subset=["Score", "Price", "Vol"]).sort_values("Score", ascending=False)
                
                # Sector Diversification
                selected, sector_counts = [], {}
                sector_limit = max(1, int(math.ceil(max_sec_w * num_pos)))
                for _, candidate in df_elig.iterrows():
                    sector = candidate["Sector"]
                    if sector_counts.get(sector, 0) < sector_limit:
                        selected.append(candidate)
                        sector_counts[sector] = sector_counts.get(sector, 0) + 1
                    if len(selected) >= num_pos: break

                # Fill remaining
                selected_symbols = {item["Stock"] for item in selected}
                if len(selected) < num_pos:
                    for _, candidate in df_elig.iterrows():
                        if candidate["Stock"] in selected_symbols: continue
                        selected.append(candidate)
                        selected_symbols.add(candidate["Stock"])
                        if len(selected) >= num_pos: break

                df_sel = pd.DataFrame(selected).reset_index(drop=True)

                # Weighting
                inv_vol = 1 / df_sel["Vol"].clip(lower=0.01)
                raw_weights = inv_vol / inv_vol.sum()
                effective_max_w = max(max_w, 1 / len(df_sel))
                df_sel["Weight"] = cap_weights(raw_weights.tolist(), effective_max_w)
                df_sel["Weight"] = df_sel["Weight"] / df_sel["Weight"].sum()

                # 100% Capital Deployment
                df_sel["Target Amount"] = df_sel["Weight"] * float(inv_amount)
                df_sel["Shares"] = np.floor(df_sel["Target Amount"] / df_sel["Price"]).astype(int)
                df_sel["Invested"] = df_sel["Shares"] * df_sel["Price"]

                remaining = round(float(inv_amount) - df_sel["Invested"].sum(), 2)
                iteration = 0
                while remaining > 0 and iteration < 10000:
                    iteration += 1
                    df_sel["Remaining Target"] = df_sel["Target Amount"] - df_sel["Invested"]
                    affordable = df_sel[df_sel["Price"] <= remaining].copy()
                    if affordable.empty: break
                    affordable = affordable.sort_values("Remaining Target", ascending=False)
                    bought = False
                    for idx in affordable.index:
                        share_price = float(df_sel.loc[idx, "Price"])
                        if share_price <= remaining:
                            df_sel.loc[idx, "Shares"] += 1
                            df_sel.loc[idx, "Invested"] += share_price
                            remaining = round(remaining - share_price, 2)
                            bought = True
                            break
                    if not bought: break

                df_sel["Stop"] = df_sel["Price"] - stop_mult * df_sel["ATR"]

                total_invested = float(df_sel["Invested"].sum())
                uninvested = round(float(inv_amount) - total_invested, 2)
                actual_weight_total = total_invested / inv_amount if inv_amount > 0 else 0

                st.write("### Portfolio Summary")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Investment Budget", f"₹{inv_amount:,.0f}")
                c2.metric("Actually Invested", f"₹{total_invested:,.2f}")
                c3.metric("Amount Remaining", f"₹{uninvested:,.2f}")
                c4.metric("Capital Deployed", f"{actual_weight_total * 100:.2f}%")

                if uninvested > 0:
                    st.warning(f"₹{uninvested:,.2f} could not buy another whole share. This is a share-unit constraint, not a cash buffer.")
                else:
                    st.success("100% of the investment budget is deployed into stocks.")

                fig_pie = px.pie(df_sel[df_sel["Invested"] > 0], values="Invested", names="Stock", hole=0.45, title="Actual Portfolio Allocation")
                fig_pie.update_layout(template="plotly_dark")
                st.plotly_chart(fig_pie, use_container_width=True)

                st.write("### Recommended Holdings")
                # Ensures columns exist for display - FIX FOR KEYERROR
                display_cols = ["Stock", "Sector", "Price", "Weight", "Shares", "Invested", "Stop", "Momentum", "3M %", "RSI", "Score"]
                df_display = df_sel[[c for c in display_cols if c in df_sel.columns]].copy()
                
                df_display["Weight"] = (df_display["Invested"] / inv_amount * 100).round(2).astype(str) + "%"
                for col in ["Price", "Invested", "Stop", "Momentum", "3M %", "RSI", "Score"]:
                    if col in df_display.columns: df_display[col] = df_display[col].round(2)

                st.dataframe(df_display, hide_index=True, use_container_width=True)
                st.download_button("⬇️ Download Portfolio CSV", df_display.to_csv(index=False), file_name="khaata_portfolio.csv", mime="text/csv")

                # Historical Risk Check
                st.write("### Reality Check — Historical Risk")
                try:
                    nifty_df = yf.download("^NSEI", period="5y", interval="1d", progress=False, auto_adjust=True)
                    if isinstance(nifty_df.columns, pd.MultiIndex): nifty_df.columns = nifty_df.columns.get_level_values(0)
                    nifty_close = nifty_df["Close"].squeeze().dropna()

                    selected_closes = {holding["Stock"]: p_data_local[holding["Stock"]]["Close"] for _, holding in df_sel.iterrows() if p_data_local.get(holding["Stock"]) is not None}
                    p_closes = pd.DataFrame(selected_closes).dropna()
                    
                    if len(p_closes) > 63 and len(nifty_close) > 63:
                        weights = df_sel.set_index("Stock")["Weight"]
                        portfolio_returns = p_closes.pct_change().mul(weights, axis=1).sum(axis=1).dropna()
                        common = pd.concat([portfolio_returns.rename("Portfolio"), nifty_close.pct_change().rename("Nifty")], axis=1, join="inner").dropna()

                        if len(common) > 63:
                            p_rets = common["Portfolio"]
                            n_rets = common["Nifty"]
                            cumulative = (1 + p_rets).cumprod()
                            
                            roll_1m = (cumulative / cumulative.shift(21) - 1).min()
                            roll_3m = (cumulative / cumulative.shift(63) - 1).min()
                            max_dd = calc_max_drawdown(p_rets)
                            ann_vol = p_rets.std() * np.sqrt(252)
                            nifty_variance = n_rets.var()
                            beta = np.cov(p_rets, n_rets)[0, 1] / nifty_variance if nifty_variance > 0 else np.nan

                            r1, r2, r3, r4, r5 = st.columns(5)
                            r1.metric("Worst 1M", f"{roll_1m * 100:.1f}%", f"₹{roll_1m * total_invested:,.0f}")
                            r2.metric("Worst 3M", f"{roll_3m * 100:.1f}%", f"₹{roll_3m * total_invested:,.0f}")
                            r3.metric("Max Drawdown", f"{max_dd * 100:.1f}%", f"₹{max_dd * total_invested:,.0f}")
                            r4.metric("Annualised Volatility", f"{ann_vol * 100:.1f}%")
                            r5.metric("Beta vs Nifty", f"{beta:.2f}" if np.isfinite(beta) else "N/A")
                            st.caption("Historical risk of today's selected stocks. This is not a return forecast.")
                except Exception as e:
                    st.warning(f"Could not calculate historical risk: {e}")

                if st.button("📤 Send Portfolio Plan to Telegram", key="pb_telegram"):
                    msg = f"<b>💼 Khaata Portfolio Plan</b>\nBudget: ₹{inv_amount:,.0f}\nInvested: ₹{total_invested:,.2f}\nRemaining: ₹{uninvested:,.2f}\nRisk: {risk}/10\nHorizon: {horizon}\n\n"
                    for _, holding in df_sel.iterrows():
                        if holding["Shares"] > 0:
                            msg += f"• <b>{holding['Stock']}</b>: {holding['Shares']} shares @ ₹{holding['Price']:.2f} (Stop ₹{holding['Stop']:.2f})\n"
                    success, err = send_telegram_message(tg_token, tg_chat_id, msg)
                    if success: st.success("Portfolio plan sent to Telegram.")
                    else: st.error(f"Telegram error: {err}")

            except Exception as e:
                st.error(f"❌ Failed to build portfolio: {e}")

    # --- TAB 8: HOT THEMES ---
    with tab_hot:
        st.subheader("🔥 Hot Themes — Thematic Investment Intelligence")
        st.caption("Curated theme research and scanner-linked market signals. Curated policy, market-cap and company mapping data are unverified estimates; verify from primary sources before acting.")

        THEME_REGISTRY = {'Defence': {'aliases': ['defense', 'arms', 'military', 'aerospace', 'hal', 'bel'], 'last_reviewed': '2026-11-26', 'verified': False, 'global_universe': [{'name': 'Lockheed Martin', 'ticker': 'LMT', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 115, 'thesis': 'F-35, missiles, space'}, {'name': 'RTX', 'ticker': 'RTX', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 165, 'thesis': 'Air defence, missiles, aerospace'}, {'name': 'Northrop Grumman', 'ticker': 'NOC', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 72, 'thesis': 'Strategic aircraft, space, systems'}, {'name': 'BAE Systems', 'ticker': 'BA.L', 'country': 'UK', 'flag': '🇬🇧', 'market_cap_usd_bn': 55, 'thesis': 'Aircraft, naval and electronic systems'}, {'name': 'Rheinmetall', 'ticker': 'RHM.DE', 'country': 'DE', 'flag': '🇩🇪', 'market_cap_usd_bn': 28, 'thesis': 'Land systems and ammunition'}, {'name': 'Hindustan Aeronautics', 'ticker': 'HAL.NS', 'country': 'IN', 'flag': '🇮🇳', 'market_cap_usd_bn': 38, 'thesis': 'Aircraft, helicopters, engines'}], 'india_direct': [{'name': 'HAL', 'ticker': 'HAL.NS', 'link': 'Aircraft mfg', 'reason': 'Tejas, helicopters, engines and aircraft upgrade programs'}, {'name': 'Bharat Electronics', 'ticker': 'BEL.NS', 'link': 'Defence electronics', 'reason': 'Radars, electronic warfare and communications'}, {'name': 'Bharat Dynamics', 'ticker': 'BDL.NS', 'link': 'Missiles', 'reason': 'Guided missiles and defence weapon systems'}, {'name': 'Mazagon Dock', 'ticker': 'MAZDOCK.NS', 'link': 'Naval shipbuilding', 'reason': 'Submarines and warship construction'}, {'name': 'Solar Industries', 'ticker': 'SOLARINDS.NS', 'link': 'Energetics', 'reason': 'Industrial explosives and defence energetics'}], 'india_indirect': [{'name': 'Data Patterns', 'ticker': 'DATAPATTNS.NS', 'link_type': 'Avionics and radar', 'reason': 'Radar, electronic warfare and aerospace subsystems'}, {'name': 'Apollo Micro Systems', 'ticker': 'APOLLO.NS', 'link_type': 'Embedded systems', 'reason': 'Embedded electronics for defence platforms'}, {'name': 'Astra Microwave', 'ticker': 'ASTRAMICRO.NS', 'link_type': 'RF/microwave', 'reason': 'RF, radar and microwave modules'}, {'name': 'MTAR Technologies', 'ticker': 'MTARTECH.NS', 'link_type': 'Precision engineering', 'reason': 'High precision components for strategic sectors'}], 'policy_kpis': [{'label': 'FY27 defence allocation (budget estimate)', 'value': '~₹6.8 lakh Cr', 'as_of': 'FY27 budget estimate; verify'}, {'label': 'FY26 defence exports', 'value': '~₹38,000 Cr', 'as_of': 'FY26 estimate; verify'}, {'label': 'Export ambition', 'value': '₹50,000 Cr', 'as_of': 'Policy target; verify'}, {'label': 'Indigenisation lists', 'value': '5,000+ items', 'as_of': 'Public policy tally; verify'}], 'policy_timeline': [{'year': 2020, 'event': 'Defence production reforms and higher FDI route announced'}, {'year': 2021, 'event': 'Positive indigenisation lists expanded'}, {'year': 2023, 'event': 'Defence exports and domestic procurement emphasis increased'}, {'year': 2025, 'event': 'Additional indigenisation and procurement initiatives'}, {'year': 2026, 'event': 'FY27 budget and export figures require primary-source confirmation'}], 'risks': [{'risk': 'Program execution and engine supply delays', 'likelihood': 3, 'impact': 5, 'category': 'Execution'}, {'risk': 'Procurement or budget slippage', 'likelihood': 2, 'impact': 4, 'category': 'Policy'}, {'risk': 'Export approvals and customer concentration', 'likelihood': 3, 'impact': 3, 'category': 'Regulatory'}, {'risk': 'Valuation and order conversion risk', 'likelihood': 4, 'impact': 4, 'category': 'Valuation'}, {'risk': 'Geopolitical cycle changes', 'likelihood': 2, 'impact': 4, 'category': 'Macro'}], 'watchlist': [{'metric': 'Defence capital outlay', 'current': 'FY27 budget figure—verify', 'threshold': 'Material reduction vs budget', 'source': 'Ministry of Defence / Union Budget', 'frequency': 'Annual'}, {'metric': 'Defence exports', 'current': 'Latest FY figure—verify', 'threshold': 'Below trend or target', 'source': 'MoD / PIB', 'frequency': 'Annual'}, {'metric': 'HAL order book', 'current': 'Company-reported—verify', 'threshold': 'Order book/annual sales below 3x', 'source': 'HAL filings', 'frequency': 'Quarterly'}, {'metric': 'BEL order inflow', 'current': 'Company-reported—verify', 'threshold': 'Inflow below revenue run-rate', 'source': 'BEL filings', 'frequency': 'Quarterly'}], 'source_urls': ['https://www.indiabudget.gov.in/', 'https://www.ibef.org/industry/defence-manufacturing']}, 'Semiconductors': {'aliases': ['chips', 'chipmaking', 'semis', 'fabs', 'silicon'], 'last_reviewed': '2026-11-26', 'verified': False, 'global_universe': [{'name': 'NVIDIA', 'ticker': 'NVDA', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 4500, 'thesis': 'AI accelerators and networking'}, {'name': 'TSMC', 'ticker': 'TSM', 'country': 'TW', 'flag': '🇹🇼', 'market_cap_usd_bn': 1500, 'thesis': 'Leading-edge foundry capacity'}, {'name': 'ASML', 'ticker': 'ASML', 'country': 'NL', 'flag': '🇳🇱', 'market_cap_usd_bn': 450, 'thesis': 'Lithography equipment bottleneck'}, {'name': 'Broadcom', 'ticker': 'AVGO', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 1300, 'thesis': 'Custom silicon and networking'}, {'name': 'AMD', 'ticker': 'AMD', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 350, 'thesis': 'CPU and AI accelerator competition'}, {'name': 'Samsung Electronics', 'ticker': '005930.KS', 'country': 'KR', 'flag': '🇰🇷', 'market_cap_usd_bn': 350, 'thesis': 'Memory, foundry and device ecosystem'}], 'india_direct': [{'name': 'Tata Elxsi', 'ticker': 'TATAELXSI.NS', 'link': 'Listed engineering proxy', 'reason': 'Tata Electronics is unlisted; Tata Elxsi is a separate listed engineering company'}, {'name': 'CG Power', 'ticker': 'CGPOWER.NS', 'link': 'OSAT / semiconductor JV', 'reason': 'Semiconductor packaging and test ecosystem investment'}, {'name': 'Kaynes Technology', 'ticker': 'KAYNES.NS', 'link': 'EMS / OSAT', 'reason': 'Electronics manufacturing and semiconductor packaging plans'}, {'name': 'SPEL Semiconductor', 'ticker': 'SPEL.NS', 'link': 'Packaging and assembly', 'reason': 'Indian semiconductor assembly and packaging exposure'}, {'name': 'MosChip Technologies', 'ticker': 'MOSCHIP.NS', 'link': 'Design services', 'reason': 'Semiconductor design and engineering services'}], 'india_indirect': [{'name': 'HCL Technologies', 'ticker': 'HCLTECH.NS', 'link_type': 'Chip design services', 'reason': 'Engineering and semiconductor design capabilities'}, {'name': 'Tata Elxsi', 'ticker': 'TATAELXSI.NS', 'link_type': 'Embedded/automotive design', 'reason': 'Embedded software and silicon-adjacent engineering'}, {'name': 'L&T', 'ticker': 'LT.NS', 'link_type': 'Infrastructure and engineering', 'reason': 'Industrial construction and technology project execution'}, {'name': 'Dixon Technologies', 'ticker': 'DIXON.NS', 'link_type': 'Electronics manufacturing', 'reason': 'Device assembly demand and electronics supply chain'}], 'policy_kpis': [{'label': 'India Semiconductor Mission', 'value': '₹76,000 Cr incentive envelope', 'as_of': 'Program announced; verify utilization'}, {'label': 'Approved projects', 'value': 'Multiple fab / ATMP projects', 'as_of': 'Nov 2026; project status verify'}, {'label': 'Global AI chip demand', 'value': 'Structural growth; cycle-sensitive', 'as_of': 'Nov 2026 estimate'}, {'label': 'India import dependence', 'value': 'High in advanced chips', 'as_of': 'Industry overview; verify'}], 'policy_timeline': [{'year': 2021, 'event': 'India Semiconductor Mission and incentive framework announced'}, {'year': 2022, 'event': 'Design-linked incentive and ecosystem programs progressed'}, {'year': 2023, 'event': 'Semiconductor project approvals and ecosystem commitments'}, {'year': 2024, 'event': 'Additional fab and ATMP project approvals announced'}, {'year': 2026, 'event': 'Construction, commissioning and yield milestones are key monitorables'}], 'risks': [{'risk': 'Fab / OSAT execution delays', 'likelihood': 4, 'impact': 5, 'category': 'Execution'}, {'risk': 'Semiconductor inventory cycle downturn', 'likelihood': 3, 'impact': 4, 'category': 'Cycle'}, {'risk': 'Technology and talent gaps', 'likelihood': 3, 'impact': 4, 'category': 'Technology'}, {'risk': 'High capital intensity / funding risk', 'likelihood': 4, 'impact': 5, 'category': 'Finance'}, {'risk': 'Export controls and geopolitical disruption', 'likelihood': 3, 'impact': 5, 'category': 'Geopolitical'}], 'watchlist': [{'metric': 'Project commissioning milestones', 'current': 'Project-specific; verify', 'threshold': 'Delay >2 quarters', 'source': 'Company / ISM announcements', 'frequency': 'Quarterly'}, {'metric': 'OSAT utilization and customer wins', 'current': 'Company disclosures', 'threshold': 'Utilization below 60% after ramp', 'source': 'Company filings', 'frequency': 'Quarterly'}, {'metric': 'DLI design wins', 'current': 'Latest disclosed count', 'threshold': 'Slower design-win conversion', 'source': 'MeitY / ISM', 'frequency': 'Quarterly'}, {'metric': 'Capex funding and cash flow', 'current': 'Project disclosures', 'threshold': 'Funding gap or cost overrun', 'source': 'Company filings', 'frequency': 'Quarterly'}], 'source_urls': ['https://www.meity.gov.in/', 'https://www.semiconductors.org/']}, 'Data Centers': {'aliases': ['datacenter', 'cloud infrastructure', 'hyperscale', 'colocation', 'ai compute'], 'last_reviewed': '2026-11-26', 'verified': False, 'global_universe': [{'name': 'Equinix', 'ticker': 'EQIX', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 90, 'thesis': 'Global colocation and interconnection'}, {'name': 'Digital Realty', 'ticker': 'DLR', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 65, 'thesis': 'Hyperscale and enterprise data centers'}, {'name': 'Vertiv', 'ticker': 'VRT', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 100, 'thesis': 'Power and cooling infrastructure'}, {'name': 'Schneider Electric', 'ticker': 'SU.PA', 'country': 'FR', 'flag': '🇫🇷', 'market_cap_usd_bn': 150, 'thesis': 'Electrical distribution and data-center efficiency'}, {'name': 'NVIDIA', 'ticker': 'NVDA', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 4500, 'thesis': 'AI compute platform demand'}, {'name': 'Microsoft', 'ticker': 'MSFT', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 4000, 'thesis': 'Cloud and AI infrastructure capex'}], 'india_direct': [{'name': 'Anant Raj', 'ticker': 'ANANTRAJ.NS', 'link': 'Data-center development', 'reason': 'Developing data-center infrastructure and capacity'}, {'name': 'Netweb Technologies', 'ticker': 'NETWEB.NS', 'link': 'Servers / HPC', 'reason': 'High-performance computing and AI server systems'}, {'name': 'Tata Communications', 'ticker': 'TATACOMM.NS', 'link': 'Connectivity / cloud', 'reason': 'Network, cloud and data-center services ecosystem'}, {'name': 'Techno Electric', 'ticker': 'TECHNOE.NS', 'link': 'Data-center projects', 'reason': 'Power infrastructure and data-center project exposure'}], 'india_indirect': [{'name': 'Larsen & Toubro', 'ticker': 'LT.NS', 'link_type': 'EPC and power systems', 'reason': 'Construction and electrical infrastructure for facilities'}, {'name': 'KEI Industries', 'ticker': 'KEI.NS', 'link_type': 'Cables', 'reason': 'Power and connectivity cable demand'}, {'name': 'Cummins India', 'ticker': 'CUMMINSIND.NS', 'link_type': 'Backup power', 'reason': 'Generator and power reliability systems'}, {'name': 'Blue Star', 'ticker': 'BLUESTARCO.NS', 'link_type': 'Cooling / HVAC', 'reason': 'Cooling systems and HVAC infrastructure'}], 'policy_kpis': [{'label': 'India data-center capacity', 'value': 'Multi-GW pipeline; verify', 'as_of': 'Nov 2026 estimate'}, {'label': 'AI / cloud demand', 'value': 'Strong structural driver', 'as_of': 'Industry outlook; verify'}, {'label': 'Power availability', 'value': 'Location-specific constraint', 'as_of': 'Current project diligence'}, {'label': 'Renewable procurement', 'value': 'Growing priority', 'as_of': 'Industry trend; verify'}], 'policy_timeline': [{'year': 2020, 'event': 'Cloud adoption and digital infrastructure investment accelerated'}, {'year': 2022, 'event': 'Data-center policies expanded across Indian states'}, {'year': 2023, 'event': 'AI workloads increased demand for high-density compute'}, {'year': 2024, 'event': 'Hyperscaler and domestic operator capacity announcements grew'}, {'year': 2026, 'event': 'Power, land, connectivity and utilization determine project economics'}], 'risks': [{'risk': 'Grid and power procurement constraints', 'likelihood': 4, 'impact': 5, 'category': 'Infrastructure'}, {'risk': 'Capex overrun and commissioning delays', 'likelihood': 3, 'impact': 4, 'category': 'Execution'}, {'risk': 'Utilization ramp slower than expected', 'likelihood': 3, 'impact': 4, 'category': 'Demand'}, {'risk': 'Cooling / water / environmental constraints', 'likelihood': 3, 'impact': 4, 'category': 'Sustainability'}, {'risk': 'Valuation and customer concentration', 'likelihood': 3, 'impact': 4, 'category': 'Valuation'}], 'watchlist': [{'metric': 'Capacity commissioned', 'current': 'Operator-reported; verify', 'threshold': 'Commissioning slips >2 quarters', 'source': 'Operator / company filings', 'frequency': 'Quarterly'}, {'metric': 'Utilization / contracted capacity', 'current': 'Not consistently disclosed', 'threshold': 'Ramp below plan', 'source': 'Company filings', 'frequency': 'Quarterly'}, {'metric': 'Power cost and availability', 'current': 'Site-specific', 'threshold': 'Power cost materially above underwriting', 'source': 'Operator / state utilities', 'frequency': 'Quarterly'}, {'metric': 'Net debt and capex', 'current': 'Company reported', 'threshold': 'Debt rises faster than contracted capacity', 'source': 'Company filings', 'frequency': 'Quarterly'}], 'source_urls': ['https://www.meity.gov.in/', 'https://www.datacenterdynamics.com/']}, 'Pharma & CDMO': {'aliases': ['pharmaceuticals', 'drug makers', 'cdmo', 'contract manufacturing', 'api'], 'last_reviewed': '2026-11-26', 'verified': False, 'global_universe': [{'name': 'Eli Lilly', 'ticker': 'LLY', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 900, 'thesis': 'Metabolic and specialty medicines'}, {'name': 'Novo Nordisk', 'ticker': 'NVO', 'country': 'DK', 'flag': '🇩🇰', 'market_cap_usd_bn': 400, 'thesis': 'GLP-1 and diabetes franchise'}, {'name': 'Lonza', 'ticker': 'LONN.SW', 'country': 'CH', 'flag': '🇨🇭', 'market_cap_usd_bn': 60, 'thesis': 'Biologics and contract development manufacturing'}, {'name': 'Merck', 'ticker': 'MRK', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 250, 'thesis': 'Oncology and pharmaceutical pipeline'}, {'name': 'Thermo Fisher', 'ticker': 'TMO', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 200, 'thesis': 'Life-science tools and services'}, {'name': 'WuXi Biologics', 'ticker': '2269.HK', 'country': 'HK', 'flag': '🇭🇰', 'market_cap_usd_bn': 25, 'thesis': 'Biologics CDMO scale and services'}], 'india_direct': [{'name': 'Syngene International', 'ticker': 'SYNGENE.NS', 'link': 'CRDMO', 'reason': 'Research, development and manufacturing services'}, {'name': "Divi's Laboratories", 'ticker': 'DIVISLAB.NS', 'link': 'API / custom synthesis', 'reason': 'Custom synthesis and API production'}, {'name': 'Sai Life Sciences', 'ticker': 'SAILIFE.NS', 'link': 'CRDMO', 'reason': 'Discovery, development and manufacturing services'}, {'name': 'Cipla', 'ticker': 'CIPLA.NS', 'link': 'Pharma', 'reason': 'Respiratory and complex generics portfolio'}, {'name': "Dr. Reddy's Laboratories", 'ticker': 'DRREDDY.NS', 'link': 'Pharma', 'reason': 'Generics, APIs and specialty products'}], 'india_indirect': [{'name': 'Laurus Labs', 'ticker': 'LAURUSLABS.NS', 'link_type': 'API / CDMO', 'reason': 'API, formulation and development manufacturing'}, {'name': 'Cohance Lifesciences', 'ticker': 'COHANCE.NS', 'link_type': 'Specialty ingredients', 'reason': 'Pharma and specialty ingredient manufacturing'}, {'name': 'Gland Pharma', 'ticker': 'GLAND.NS', 'link_type': 'Injectables', 'reason': 'Sterile injectable manufacturing scale'}, {'name': 'Aurobindo Pharma', 'ticker': 'AUROPHARMA.NS', 'link_type': 'Generics / API', 'reason': 'Vertical integration and global generic supply'}], 'policy_kpis': [{'label': 'Indian pharma exports', 'value': '~$27B annual scale', 'as_of': 'Recent FY benchmark; verify'}, {'label': 'PLI pharma scheme', 'value': '₹15,000 Cr outlay', 'as_of': 'Scheme allocation; verify'}, {'label': 'CDMO demand', 'value': 'Outsourcing / China+1', 'as_of': 'Industry trend'}, {'label': 'Quality compliance', 'value': 'USFDA / EU GMP critical', 'as_of': 'Ongoing inspections'}], 'policy_timeline': [{'year': 2020, 'event': 'Pharma PLI schemes announced for domestic manufacturing'}, {'year': 2021, 'event': 'PLI implementation and eligible product investments progressed'}, {'year': 2022, 'event': 'Global supply-chain diversification boosted outsourcing interest'}, {'year': 2024, 'event': 'Quality upgrades and specialty manufacturing remained sector focus'}, {'year': 2026, 'event': 'CDMO capacity utilization, customer wins and compliance are key'}], 'risks': [{'risk': 'Regulatory warning letters / observations', 'likelihood': 3, 'impact': 5, 'category': 'Regulatory'}, {'risk': 'Customer program cancellations', 'likelihood': 3, 'impact': 4, 'category': 'Demand'}, {'risk': 'Pricing pressure in generics', 'likelihood': 4, 'impact': 3, 'category': 'Competition'}, {'risk': 'R&D and facility ramp underperformance', 'likelihood': 3, 'impact': 4, 'category': 'Execution'}, {'risk': 'Currency and export-market exposure', 'likelihood': 3, 'impact': 3, 'category': 'Macro'}], 'watchlist': [{'metric': 'CDMO order book / client wins', 'current': 'Company disclosure', 'threshold': 'Two quarters of weak growth', 'source': 'Company filings / calls', 'frequency': 'Quarterly'}, {'metric': 'Facility utilization', 'current': 'Company reported', 'threshold': 'Below 65% at mature facilities', 'source': 'Company filings', 'frequency': 'Quarterly'}, {'metric': 'Regulatory inspections', 'current': 'Inspection status varies', 'threshold': 'Major warning / import restriction', 'source': 'USFDA / regulators', 'frequency': 'Event-driven'}, {'metric': 'Export revenue and margins', 'current': 'Company reported', 'threshold': 'Margin contraction >300 bps', 'source': 'Company filings', 'frequency': 'Quarterly'}], 'source_urls': ['https://www.pharmaceuticals.gov.in/', 'https://www.ibef.org/industry/pharmaceutical-india']}, 'Power & Energy Transition': {'aliases': ['renewables', 'solar', 'wind', 'grid', 'energy transition'], 'last_reviewed': '2026-11-26', 'verified': False, 'global_universe': [{'name': 'NextEra Energy', 'ticker': 'NEE', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 150, 'thesis': 'Renewable generation and regulated utility'}, {'name': 'GE Vernova', 'ticker': 'GEV', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 120, 'thesis': 'Grid, wind and power equipment'}, {'name': 'Siemens Energy', 'ticker': 'ENR.DE', 'country': 'DE', 'flag': '🇩🇪', 'market_cap_usd_bn': 80, 'thesis': 'Grid technology and generation systems'}, {'name': 'Enphase Energy', 'ticker': 'ENPH', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 15, 'thesis': 'Solar inverter and energy management'}, {'name': 'Iberdrola', 'ticker': 'IBE.MC', 'country': 'ES', 'flag': '🇪🇸', 'market_cap_usd_bn': 100, 'thesis': 'Renewables and regulated networks'}, {'name': 'BYD', 'ticker': '1211.HK', 'country': 'CN', 'flag': '🇨🇳', 'market_cap_usd_bn': 120, 'thesis': 'EVs, batteries and electrification'}], 'india_direct': [{'name': 'Adani Green Energy', 'ticker': 'ADANIGREEN.NS', 'link': 'Renewable generation', 'reason': 'Utility-scale solar, wind and hybrid projects'}, {'name': 'NTPC', 'ticker': 'NTPC.NS', 'link': 'Power generation / renewables', 'reason': 'Large power base and renewable capacity expansion'}, {'name': 'Tata Power', 'ticker': 'TATAPOWER.NS', 'link': 'Integrated power / solar', 'reason': 'Renewables, distribution, solar and charging'}, {'name': 'Suzlon Energy', 'ticker': 'SUZLON.NS', 'link': 'Wind equipment', 'reason': 'Wind turbine manufacturing and service'}, {'name': 'JSW Energy', 'ticker': 'JSWENERGY.NS', 'link': 'Power / storage', 'reason': 'Generation, renewables and storage pipeline'}], 'india_indirect': [{'name': 'Power Grid Corporation', 'ticker': 'POWERGRID.NS', 'link_type': 'Transmission', 'reason': 'Grid transmission capex and renewable integration'}, {'name': 'BHEL', 'ticker': 'BHEL.NS', 'link_type': 'Power equipment', 'reason': 'Generation equipment and grid-related engineering'}, {'name': 'Waaree Energies', 'ticker': 'WAAREEENER.NS', 'link_type': 'Solar modules', 'reason': 'Solar module manufacturing and supply chain'}, {'name': 'INOX Wind', 'ticker': 'INOXWIND.NS', 'link_type': 'Wind equipment', 'reason': 'Wind turbine supply, installation and service'}], 'policy_kpis': [{'label': 'Renewable capacity target', 'value': '500 GW non-fossil by 2030', 'as_of': 'National target; verify progress'}, {'label': 'Solar capacity additions', 'value': 'Annual record additions expected', 'as_of': '2026 estimate; verify'}, {'label': 'Grid capex', 'value': 'Multi-year expansion', 'as_of': 'Plan / project pipeline'}, {'label': 'Storage requirement', 'value': 'Growing with renewables', 'as_of': 'Industry outlook'}], 'policy_timeline': [{'year': 2015, 'event': 'Renewable energy targets and solar mission expanded'}, {'year': 2021, 'event': 'Updated climate and non-fossil capacity commitments'}, {'year': 2022, 'event': 'Green hydrogen mission and transition programs advanced'}, {'year': 2023, 'event': 'Renewable bidding and transmission expansion continued'}, {'year': 2026, 'event': 'Grid, storage, execution and power offtake shape returns'}], 'risks': [{'risk': 'Grid curtailment and transmission bottlenecks', 'likelihood': 3, 'impact': 4, 'category': 'Infrastructure'}, {'risk': 'Tariff / tender changes', 'likelihood': 3, 'impact': 4, 'category': 'Policy'}, {'risk': 'High interest rates and project financing', 'likelihood': 3, 'impact': 5, 'category': 'Finance'}, {'risk': 'Equipment pricing and supply-chain pressure', 'likelihood': 3, 'impact': 3, 'category': 'Competition'}, {'risk': 'Weather and resource variability', 'likelihood': 3, 'impact': 3, 'category': 'Operating'}], 'watchlist': [{'metric': 'Renewable capacity commissioning', 'current': 'Latest MNRE data—verify', 'threshold': 'Commissioning below plan by >10%', 'source': 'MNRE / company filings', 'frequency': 'Monthly / quarterly'}, {'metric': 'Order book and tender wins', 'current': 'Company disclosed', 'threshold': 'Order inflow below revenue', 'source': 'Company filings', 'frequency': 'Quarterly'}, {'metric': 'Receivables / payment cycle', 'current': 'Company reported', 'threshold': 'Receivable days rise materially', 'source': 'Company filings', 'frequency': 'Quarterly'}, {'metric': 'Debt and project returns', 'current': 'Company reported', 'threshold': 'Net debt/EBITDA exceeds plan', 'source': 'Company filings', 'frequency': 'Quarterly'}], 'source_urls': ['https://mnre.gov.in/', 'https://www.cea.nic.in/']}, 'Capital Markets & Financials': {'aliases': ['banks', 'financial services', 'broking', 'insurance', 'capital markets'], 'last_reviewed': '2026-11-26', 'verified': False, 'global_universe': [{'name': 'JPMorgan Chase', 'ticker': 'JPM', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 800, 'thesis': 'Universal banking and capital markets'}, {'name': 'Goldman Sachs', 'ticker': 'GS', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 200, 'thesis': 'Investment banking and trading'}, {'name': 'BlackRock', 'ticker': 'BLK', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 150, 'thesis': 'Asset management and ETF flows'}, {'name': 'Visa', 'ticker': 'V', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 700, 'thesis': 'Payments network and transaction growth'}, {'name': 'London Stock Exchange Group', 'ticker': 'LSEG.L', 'country': 'UK', 'flag': '🇬🇧', 'market_cap_usd_bn': 60, 'thesis': 'Market data, analytics and exchange services'}, {'name': 'CME Group', 'ticker': 'CME', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 100, 'thesis': 'Derivatives and clearing'}], 'india_direct': [{'name': 'BSE', 'ticker': 'BSE.NS', 'link': 'Exchange', 'reason': 'Cash, derivatives and listing activity'}, {'name': 'NSE (unlisted proxy: N/A)', 'ticker': 'BSE.NS', 'link': 'Listed exchange proxy', 'reason': 'NSE is unlisted; BSE provides listed exchange exposure'}, {'name': 'Angel One', 'ticker': 'ANGELONE.NS', 'link': 'Retail broking', 'reason': 'Active retail participation and trading volumes'}, {'name': 'ICICI Securities (delisted; use ICICI Bank)', 'ticker': 'ICICIBANK.NS', 'link': 'Bank / financial services proxy', 'reason': 'ICICI Securities delisted; bank group proxy used'}, {'name': 'HDFC Bank', 'ticker': 'HDFCBANK.NS', 'link': 'Banking', 'reason': 'Deposit franchise, credit growth and financial ecosystem'}], 'india_indirect': [{'name': 'CAMS', 'ticker': 'CAMS.NS', 'link_type': 'Mutual fund services', 'reason': 'Asset servicing and fund industry infrastructure'}, {'name': 'KFin Technologies', 'ticker': 'KFINTECH.NS', 'link_type': 'Registrar / fund services', 'reason': 'Issuer, mutual fund and investor servicing'}, {'name': 'CDSL', 'ticker': 'CDSL.NS', 'link_type': 'Depository', 'reason': 'Demat accounts and securities settlement ecosystem'}, {'name': 'CRISIL', 'ticker': 'CRISIL.NS', 'link_type': 'Ratings / analytics', 'reason': 'Credit ratings, research and analytics'}], 'policy_kpis': [{'label': 'Demat accounts', 'value': 'Record scale; latest figure verify', 'as_of': '2026 estimate'}, {'label': 'Mutual fund AUM', 'value': 'Large and growing base; verify', 'as_of': 'Latest AMFI data'}, {'label': 'Exchange turnover', 'value': 'Cycle-dependent', 'as_of': 'Latest exchange data'}, {'label': 'Bank credit growth', 'value': 'Monitor against deposits', 'as_of': 'Latest RBI data'}], 'policy_timeline': [{'year': 2020, 'event': 'Digital finance and market participation accelerated'}, {'year': 2021, 'event': 'Retail accounts and market activity expanded'}, {'year': 2022, 'event': 'RBI digital payments and regulatory framework evolved'}, {'year': 2024, 'event': 'Market infrastructure, investor protection and derivatives rules updated'}, {'year': 2026, 'event': 'Turnover, AUM, credit, fee yields and regulation drive sector outlook'}], 'risks': [{'risk': 'Trading activity normalizes after high volumes', 'likelihood': 4, 'impact': 4, 'category': 'Cycle'}, {'risk': 'Regulatory restrictions on derivatives / fees', 'likelihood': 3, 'impact': 4, 'category': 'Regulatory'}, {'risk': 'Credit stress and asset quality deterioration', 'likelihood': 3, 'impact': 5, 'category': 'Credit'}, {'risk': 'Deposit competition and margin compression', 'likelihood': 4, 'impact': 4, 'category': 'Banking'}, {'risk': 'Market drawdown reduces AUM and flows', 'likelihood': 3, 'impact': 4, 'category': 'Market'}], 'watchlist': [{'metric': 'Exchange turnover / volumes', 'current': 'Latest exchange data—verify', 'threshold': '3-month average falls >20% YoY', 'source': 'BSE / NSE', 'frequency': 'Monthly'}, {'metric': 'Mutual fund net flows and AUM', 'current': 'AMFI monthly report', 'threshold': 'Two months of net outflows', 'source': 'AMFI', 'frequency': 'Monthly'}, {'metric': 'Bank NIM and credit growth', 'current': 'Quarterly disclosures', 'threshold': 'NIM down >50 bps or credit quality weakens', 'source': 'Bank filings / RBI', 'frequency': 'Quarterly'}, {'metric': 'Regulatory actions', 'current': 'Monitor circulars', 'threshold': 'Material restriction on core revenue', 'source': 'SEBI / RBI', 'frequency': 'Event-driven'}], 'source_urls': ['https://www.sebi.gov.in/', 'https://www.amfiindia.com/']}, 'Manufacturing & Import Substitution': {'aliases': ['make in india', 'local manufacturing', 'p li', 'indigenisation', 'import substitution'], 'last_reviewed': '2026-11-26', 'verified': False, 'global_universe': [{'name': 'Siemens', 'ticker': 'SIE.DE', 'country': 'DE', 'flag': '🇩🇪', 'market_cap_usd_bn': 200, 'thesis': 'Industrial automation and electrification'}, {'name': 'Honeywell', 'ticker': 'HON', 'country': 'US', 'flag': '🇺🇸', 'market_cap_usd_bn': 150, 'thesis': 'Automation, aerospace and industrial systems'}, {'name': 'Schneider Electric', 'ticker': 'SU.PA', 'country': 'FR', 'flag': '🇫🇷', 'market_cap_usd_bn': 150, 'thesis': 'Automation and energy management'}, {'name': 'ABB', 'ticker': 'ABB', 'country': 'CH', 'flag': '🇨🇭', 'market_cap_usd_bn': 120, 'thesis': 'Robotics, electrification and automation'}, {'name': 'CATL', 'ticker': '300750.SZ', 'country': 'CN', 'flag': '🇨🇳', 'market_cap_usd_bn': 150, 'thesis': 'Battery manufacturing scale'}, {'name': 'Toyota', 'ticker': '7203.T', 'country': 'JP', 'flag': '🇯🇵', 'market_cap_usd_bn': 300, 'thesis': 'Automotive manufacturing and supply chain'}], 'india_direct': [{'name': 'Bharat Forge', 'ticker': 'BHARATFORG.NS', 'link': 'Forging / engineering', 'reason': 'Precision forgings and industrial / mobility components'}, {'name': 'Dixon Technologies', 'ticker': 'DIXON.NS', 'link': 'Electronics manufacturing', 'reason': 'EMS scale, customer programs and localization'}, {'name': 'Kaynes Technology', 'ticker': 'KAYNES.NS', 'link': 'EMS / advanced manufacturing', 'reason': 'Electronics manufacturing and higher-value systems'}, {'name': 'Amber Enterprises', 'ticker': 'AMBER.NS', 'link': 'Components / electronics', 'reason': 'AC components and electronics manufacturing'}, {'name': 'Hindustan Zinc', 'ticker': 'HINDZINC.NS', 'link': 'Domestic metals supply', 'reason': 'Domestic zinc and silver production / import replacement'}], 'india_indirect': [{'name': 'Larsen & Toubro', 'ticker': 'LT.NS', 'link_type': 'Industrial EPC', 'reason': 'Factories, infrastructure and industrial project execution'}, {'name': 'Cummins India', 'ticker': 'CUMMINSIND.NS', 'link_type': 'Power equipment', 'reason': 'Engine and power systems manufacturing'}, {'name': 'Polycab India', 'ticker': 'POLYCAB.NS', 'link_type': 'Electrical products', 'reason': 'Cables and wires for industrial capex'}, {'name': 'Motherson', 'ticker': 'MOTHERSON.NS', 'link_type': 'Auto components', 'reason': 'Globalized automotive component manufacturing footprint'}], 'policy_kpis': [{'label': 'Manufacturing share of GDP', 'value': 'Target ~25%; current below target', 'as_of': 'Policy ambition; verify'}, {'label': 'PLI schemes', 'value': 'Multiple sectors / schemes', 'as_of': 'Scheme status varies'}, {'label': 'Electronics exports', 'value': 'Growing rapidly; verify latest', 'as_of': 'FY26/FY27 estimate'}, {'label': 'Import dependence', 'value': 'Sector-specific; monitor', 'as_of': 'Trade data'}], 'policy_timeline': [{'year': 2014, 'event': 'Make in India initiative launched'}, {'year': 2020, 'event': 'Production-linked incentive schemes introduced across sectors'}, {'year': 2021, 'event': 'PLI programs and domestic manufacturing incentives expanded'}, {'year': 2023, 'event': 'Electronics, mobility and industrial supply-chain investments grew'}, {'year': 2026, 'event': 'Localization, export competitiveness and execution remain key measures'}], 'risks': [{'risk': 'Policy incentives change or lapse', 'likelihood': 3, 'impact': 4, 'category': 'Policy'}, {'risk': 'Imported input dependence persists', 'likelihood': 4, 'impact': 4, 'category': 'Supply chain'}, {'risk': 'Low margins / intense EMS competition', 'likelihood': 4, 'impact': 4, 'category': 'Competition'}, {'risk': 'Customer concentration and program volatility', 'likelihood': 3, 'impact': 4, 'category': 'Demand'}, {'risk': 'Capex and working-capital strain', 'likelihood': 3, 'impact': 5, 'category': 'Finance'}], 'watchlist': [{'metric': 'Domestic value-add / localization', 'current': 'Company and sector disclosures', 'threshold': 'Localization progress stalls', 'source': 'Company filings / industry bodies', 'frequency': 'Annual / quarterly'}, {'metric': 'PLI incentive receipts', 'current': 'Scheme-specific disclosures', 'threshold': 'Eligibility or payout delay', 'source': 'Ministry / company filings', 'frequency': 'Quarterly'}, {'metric': 'Order book and capacity utilization', 'current': 'Company reported', 'threshold': 'Utilization below 65% or order weakness', 'source': 'Company filings', 'frequency': 'Quarterly'}, {'metric': 'Working capital / cash conversion', 'current': 'Company reported', 'threshold': 'Receivable days increase >20% YoY', 'source': 'Company filings', 'frequency': 'Quarterly'}], 'source_urls': ['https://www.makeinindia.com/', 'https://www.investindia.gov.in/']}}

        theme_names = list(THEME_REGISTRY.keys())
        theme_labels = ["🛡️ Defence", "💻 Semiconductors", "🖥️ Data Centers", "💊 Pharma & CDMO", "⚡ Power & Energy Transition", "🏦 Capital Markets & Financials", "🏭 Manufacturing & Import Substitution"]
        label_to_theme = dict(zip(theme_labels, theme_names))
        selected_label = st.radio("Choose theme", theme_labels, horizontal=True, key="hot_theme_choice")
        selected_theme = label_to_theme[selected_label]
        theme = THEME_REGISTRY[selected_theme]

        # Theme-level scanner metrics from stocks available in the existing scan.
        direct_symbols = [x["ticker"].replace(".NS", "") for x in theme["india_direct"]]
        indirect_symbols = [x["ticker"].replace(".NS", "") for x in theme["india_indirect"]]
        all_theme_symbols = list(dict.fromkeys(direct_symbols + indirect_symbols))
        theme_df = df[df["Stock"].isin(all_theme_symbols)].copy()
        available = len(theme_df)
        avg_mom = float(theme_df["Momentum"].mean()) if available else np.nan
        avg_1m = float(theme_df["1M %"].mean()) if available else np.nan
        avg_1y = float(theme_df["1Y %"].mean()) if available else np.nan
        breadth = float((theme_df["Long Trend"] == "🟢 Bullish").mean() * 100) if available and "Long Trend" in theme_df else np.nan
        st.caption(f"Theme data review: {theme['last_reviewed']} | Curated data verified: {theme['verified']} | Scanner-linked stocks available: {available}/{len(all_theme_symbols)}")

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Avg Momentum", f"{avg_mom:+.1f}" if np.isfinite(avg_mom) else "N/A")
        k2.metric("Avg 1M Return", f"{avg_1m:+.1f}%" if np.isfinite(avg_1m) else "N/A")
        k3.metric("Avg 1Y Return", f"{avg_1y:+.1f}%" if np.isfinite(avg_1y) else "N/A")
        k4.metric("Breadth (>200DMA)", f"{breadth:.0f}%" if np.isfinite(breadth) else "N/A")
        k5.metric("Stocks available", f"{available}/{len(all_theme_symbols)}")

        st.markdown("### Theme performance and stock breadth")
        if not theme_df.empty:
            perf_cols = [c for c in ["Stock", "Sector", "Price", "1M %", "3M %", "6M %", "1Y %", "Momentum", "Trend", "Long Trend", "Vol"] if c in theme_df.columns]
            perf = theme_df[perf_cols].sort_values("Momentum", ascending=False)
            fig_perf = px.bar(perf, x="Stock", y="Momentum", color="Momentum", color_continuous_scale="RdYlGn", title="Scanner Momentum — theme stocks")
            fig_perf.update_layout(template="plotly_dark")
            st.plotly_chart(fig_perf, use_container_width=True)
            st.dataframe(perf, hide_index=True, use_container_width=True)
        else:
            st.warning("No stocks from this theme are present in the current scanner results. Run the scanner first, or check NSE ticker coverage.")

        st.markdown("### Global leaders")
        global_df = pd.DataFrame(theme["global_universe"])
        st.dataframe(global_df, hide_index=True, use_container_width=True)
        if "market_cap_usd_bn" in global_df.columns:
            fig_global = px.bar(global_df, x="name", y="market_cap_usd_bn", color="country", title="Curated global market-cap estimates (USD bn)")
            fig_global.update_layout(template="plotly_dark", xaxis_title="Company", yaxis_title="Estimated market cap (USD bn)")
            st.plotly_chart(fig_global, use_container_width=True)

        st.markdown("### India direct and indirect plays")
        c_direct, c_indirect = st.columns(2)
        with c_direct:
            st.markdown("**Direct exposure**")
            direct_df = pd.DataFrame(theme["india_direct"])
            st.dataframe(direct_df, hide_index=True, use_container_width=True)
        with c_indirect:
            st.markdown("**Indirect / value-chain exposure**")
            indirect_df = pd.DataFrame(theme["india_indirect"])
            st.dataframe(indirect_df, hide_index=True, use_container_width=True)

        # RSI is computed only for scanner stocks with downloaded price history.
        rsi_rows = []
        price_data = st.session_state.get("p_data", {})
        for sym in all_theme_symbols:
            history = price_data.get(sym)
            if history is None or len(history) < 20: continue
            try:
                rsi_value = float(ta.momentum.RSIIndicator(history["Close"].astype(float), window=14).rsi().iloc[-1])
                stock_row = df[df["Stock"] == sym]
                rsi_rows.append({"Stock": sym, "RSI 14": round(rsi_value, 1), "Momentum": float(stock_row["Momentum"].iloc[0]) if not stock_row.empty else np.nan})
            except Exception: pass
        if rsi_rows:
            st.markdown("**Technical snapshot (available NSE stocks)**")
            st.dataframe(pd.DataFrame(rsi_rows).sort_values("Momentum", ascending=False), hide_index=True, use_container_width=True)

        st.markdown("### Policy KPIs and catalysts")
        kpi_cols = st.columns(len(theme["policy_kpis"]))
        for col, item in zip(kpi_cols, theme["policy_kpis"]):
            col.metric(item["label"], item["value"])
            col.caption(item["as_of"])
        timeline_df = pd.DataFrame(theme["policy_timeline"])
        st.dataframe(timeline_df, hide_index=True, use_container_width=True)

        st.markdown("### Ecosystem map")
        # Simple interactive node layout: central theme connected to direct and indirect names.
        names_direct = [item["name"] for item in theme["india_direct"]]
        names_indirect = [item["name"] for item in theme["india_indirect"]]
        nodes = [(selected_theme, 0, 0, "Theme")] + [(n, -1, i - (len(names_direct)-1)/2, "Direct") for i, n in enumerate(names_direct)] + [(n, 1, i - (len(names_indirect)-1)/2, "Indirect") for i, n in enumerate(names_indirect)]
        edge_x, edge_y = [], []
        for n in nodes[1:]: edge_x += [0, n[1], None]; edge_y += [0, n[2], None]
        fig_net = go.Figure()
        fig_net.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines", line=dict(color="gray", width=1), hoverinfo="skip", showlegend=False))
        for group in ["Theme", "Direct", "Indirect"]:
            subset = [n for n in nodes if n[3] == group]
            fig_net.add_trace(go.Scatter(x=[n[1] for n in subset], y=[n[2] for n in subset], mode="markers+text", text=[n[0] for n in subset], textposition="middle right" if group != "Direct" else "middle left", name=group, marker=dict(size=22 if group == "Theme" else 14), hovertext=[n[0] for n in subset], hoverinfo="text"))
        fig_net.update_layout(template="plotly_dark", height=420, title="Theme value-chain relationships", xaxis=dict(visible=False), yaxis=dict(visible=False), showlegend=True)
        st.plotly_chart(fig_net, use_container_width=True)

        st.markdown("### Correlation heatmap (scanner stocks)")
        correlation_symbols = [sym for sym in all_theme_symbols if sym in price_data and len(price_data[sym]) > 30]
        if len(correlation_symbols) >= 2:
            returns_df = pd.DataFrame({sym: price_data[sym]["Close"].pct_change() for sym in correlation_symbols}).dropna()
            if len(returns_df) >= 20:
                fig_corr = px.imshow(returns_df.corr(), color_continuous_scale="RdBu", zmin=-1, zmax=1, title="Daily-return correlation")
                fig_corr.update_layout(template="plotly_dark")
                st.plotly_chart(fig_corr, use_container_width=True)
            else: st.info("Not enough overlapping return history for correlation analysis.")
        else: st.info("At least two theme stocks with downloaded price history are needed for the correlation heatmap.")

        st.markdown("### Risks and monitoring")
        risk_df = pd.DataFrame(theme["risks"])
        if not risk_df.empty:
            fig_risk = px.scatter(risk_df, x="likelihood", y="impact", color="category", hover_name="risk", text="risk", title="Risk likelihood vs impact (1–5)")
            fig_risk.update_layout(template="plotly_dark", xaxis=dict(range=[0.5, 5.5], dtick=1, title="Likelihood"), yaxis=dict(range=[0.5, 5.5], dtick=1, title="Impact"))
            st.plotly_chart(fig_risk, use_container_width=True)
            st.dataframe(risk_df, hide_index=True, use_container_width=True)
        st.dataframe(pd.DataFrame(theme["watchlist"]), hide_index=True, use_container_width=True)
        st.markdown("### Source links")
        for source_url in theme["source_urls"]:
            st.markdown(f"- {source_url}")
