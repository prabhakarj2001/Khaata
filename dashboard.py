import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
import requests
import io
import ta

st.set_page_config(page_title="Market Master Scanner", layout="wide")
st.title("📈 Ultimate Market & Sector Scanner")

# Timeline map: label -> trading days
PERIODS = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252, "3Y": 756, "5Y": 1260}
METALS = {'Gold': 'GC=F', 'Silver': 'SI=F', 'Copper': 'HG=F', 'Platinum': 'PL=F', 'Palladium': 'PA=F'}

# ==========================================
# --- CURRENT MARKET DRIVERS ---
# ==========================================
with st.expander("🚨 Current Market Drivers & Risks (Click to expand)", expanded=False):
    current_topics = [
        {"Topic": "Record FPI Inflows", "Detail": "FPIs poured massive capital into Indian equities recently.", "Market Impact": "🟢 Bullish"},
        {"Topic": "Inflation & RBI Rate Hikes", "Detail": "Retail inflation remains a concern. Rate hikes pressure valuations.", "Market Impact": "🔴 Bearish"},
        {"Topic": "Crude Oil & Geopolitics", "Detail": "Oil price spikes hurt India's import bill and the Rupee.", "Market Impact": "🔴 Bearish"},
        {"Topic": "Global AI Stock Rotation", "Detail": "Sell-off in global tech drives funds into Indian IT.", "Market Impact": "🟢 Bullish"},
        {"Topic": "Earnings & Valuations", "Detail": "Markets watching if earnings justify high valuations.", "Market Impact": "⚪ Neutral"}
    ]
    st.dataframe(pd.DataFrame(current_topics), use_container_width=True, hide_index=True)

# ==========================================
# --- TELEGRAM (SPLITS LONG MESSAGES) ---
# ==========================================
def send_telegram_message(token, chat_id, message):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        if len(message) <= 4000:
            payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
            response = requests.post(url, json=payload)
            return response.status_code == 200, response.json().get('description', 'Error')

        lines = message.split('\n')
        current_chunk, success, error_msg = "", True, ""
        for line in lines:
            if len(current_chunk) + len(line) + 1 > 4000:
                response = requests.post(url, json={"chat_id": chat_id, "text": current_chunk, "parse_mode": "HTML"})
                if response.status_code != 200:
                    success, error_msg = False, response.json().get('description', 'Error')
                current_chunk = line + "\n"
            else:
                current_chunk += line + "\n"
        if current_chunk.strip():
            response = requests.post(url, json={"chat_id": chat_id, "text": current_chunk, "parse_mode": "HTML"})
            if response.status_code != 200:
                success, error_msg = False, response.json().get('description', 'Error')
        return success, error_msg
    except Exception as e:
        return False, str(e)

# ---- Alert prioritisation ----
SIGNAL_ORDER = ["STRONG SELL", "STRONG BUY", "WEAK SELL", "WEAK BUY"]
SIGNAL_EMOJI = {"STRONG SELL": "🔴", "STRONG BUY": "🟢", "WEAK SELL": "🟠", "WEAK BUY": "🟡"}

def allocate_alerts(sig_list, cap):
    """1) STRONG SELL gets first claim on every slot.
       2) Leftover slots split equally across STRONG BUY / WEAK SELL / WEAK BUY,
          best-impact first inside each bucket. Unused share is redistributed."""
    groups = {k: sorted([s for s in sig_list if s["Type"] == k], key=lambda x: x["Impact"], reverse=True)
              for k in SIGNAL_ORDER}
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
    msg = f"<b>🚨 Buy/Sell Alerts</b> ({shown} of {len(sig_list)} shown, ranked by impact)\n"
    for k in SIGNAL_ORDER:
        if not picked[k]:
            continue
        extra = len(groups[k]) - len(picked[k])
        more = f" (+{extra} more)" if extra > 0 else ""
        msg += f"\n<b>{SIGNAL_EMOJI[k]} {k} — {len(groups[k])}{more}</b>\n"
        for s in picked[k]:
            msg += f"• {s['Stock']} ₹{s['Price']} | RSI {s['RSI']} | {s['Hold Time']}\n"
    return msg

# ==========================================
# --- SIDEBAR CONTROLS ---
# ==========================================
st.sidebar.header("📱 Telegram Alerts")
# Token lives in .streamlit/secrets.toml (TG_TOKEN, TG_CHAT_ID) -- never hardcode it
tg_token = st.sidebar.text_input("Bot Token", type="password", value=st.secrets.get("TG_TOKEN", ""))
tg_chat_id = st.sidebar.text_input("Chat ID", value=st.secrets.get("TG_CHAT_ID", ""))
tg_cap = st.sidebar.slider("Max stocks per alert", 10, 100, 30, step=5,
                           help="Strong Sells fill first. Leftover slots split equally across Strong Buy / Weak Sell / Weak Buy.")

# ==========================================
# --- DATA FETCHING ---
# ==========================================
@st.cache_data(ttl=86400)
def get_nse_data():
    try:
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        df = pd.read_csv(io.StringIO(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10).text))
        return df['Symbol'].tolist(), dict(zip(df['Symbol'], df['Industry']))
    except:
        return ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"], {s: "Unknown" for s in ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"]}

def get_ret(df, days):
    if len(df) > 1:
        actual_days = min(days, len(df) - 1)
        if actual_days > 0:
            return ((df['Close'].iloc[-1] - df['Close'].iloc[-actual_days]) / df['Close'].iloc[-actual_days]) * 100
    return 0.0

@st.cache_data(ttl=3600)
def download_data(symbols, period="5y"):
    all_data = {}
    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i+50]
        tickers = [s + ".NS" if not s.endswith(".NS") else s for s in chunk]
        try:
            data = yf.download(tickers, period=period, interval="1d", group_by='ticker', progress=False, threads=True)
            if not data.empty:
                for orig_sym, clean_sym in zip(chunk, tickers):
                    if isinstance(data.columns, pd.MultiIndex) and clean_sym in data.columns.levels[0]:
                        df = data[clean_sym].dropna()
                        if not df.empty: all_data[orig_sym] = df
                    elif not isinstance(data.columns, pd.MultiIndex) and len(chunk) == 1:
                        df = data.dropna()
                        if not df.empty: all_data[orig_sym] = df
        except: pass
    return all_data

@st.cache_data(ttl=3600)
def get_metals(period="5y"):
    out = {}
    for name, ticker in METALS.items():
        try:
            d = yf.download(ticker, period=period, interval="1d", progress=False)
            if d.empty: continue
            if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
            out[name] = d.dropna()
        except: pass
    return out

# ==========================================
# --- MAIN LOGIC ---
# ==========================================
if st.button("🚀 Fetch Nifty 500 Data & Build Dashboard"):
    all_syms, nse_map = get_nse_data()
    all_syms = [s for s in all_syms if "&" not in s]  # Skip M&M

    with st.spinner(f"Downloading Data for all {len(all_syms)} Nifty 500 stocks... (Takes ~15 seconds)"):
        p_data = download_data(all_syms, period="5y")

        results = []
        for sym in all_syms:
            df = p_data.get(sym)
            if df is None or len(df) < 50: continue

            price = df['Close'].iloc[-1]
            r = {p: get_ret(df, d) for p, d in PERIODS.items()}
            mom = (r["1M"] * 0.2) + (r["6M"] * 0.3) + (r["1Y"] * 0.5)
            trend = "🟢 Up" if price > df['Close'].rolling(50).mean().iloc[-1] else "🔴 Down"
            vol_spike = "🚨 SPIKE" if df['Volume'].iloc[-1] > (2 * df['Volume'].rolling(20).mean().iloc[-1]) else "Normal"

            row = {"Stock": sym.replace(".NS", ""), "Sector": nse_map.get(sym.replace(".NS", ""), "Other"),
                   "Price": round(float(price), 2)}
            for p in PERIODS:
                row[f"{p} %"] = round(float(r[p]), 1)
            row.update({"Momentum": round(float(mom), 1), "Trend": trend, "Vol": vol_spike})
            results.append(row)

        st.session_state.df = pd.DataFrame(results)
        st.session_state.p_data = p_data
        st.success(f"✅ Successfully downloaded {len(results)} stocks!")

# ==========================================
# --- RENDER TABS ---
# ==========================================
if 'df' in st.session_state and not st.session_state.df.empty:
    df = st.session_state.df

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📉 Sensex", "🏆 Top 10", "📊 Scanner", "🏢 Sectors", "🥇 Metals", "📈 Buy/Sell"
    ])

    # --- TAB 1: SENSEX ---
    with tab1:
        st.subheader("📉 Sensex Performance")
        s_df = yf.download("^BSESN", period="1y", interval="1d", progress=False)
        if not s_df.empty:
            if isinstance(s_df.columns, pd.MultiIndex): s_df.columns = s_df.columns.get_level_values(0)
            fig_s = go.Figure(data=[go.Candlestick(x=s_df.dropna().index, open=s_df['Open'], high=s_df['High'], low=s_df['Low'], close=s_df['Close'])])
            fig_s.update_layout(template="plotly_dark", xaxis_rangeslider_visible=False, height=400, title="Sensex 1-Year Chart")
            st.plotly_chart(fig_s, use_container_width=True)

    # --- TAB 2: TOP 10 ---
    with tab2:
        st.subheader("🏆 Top 10 Multi-Period Performers")
        top10 = df.sort_values(by="Momentum", ascending=False).head(10)
        st.dataframe(top10[["Stock", "Sector", "Price", "1M %", "3M %", "6M %", "1Y %", "3Y %", "5Y %", "Momentum"]], use_container_width=True, hide_index=True)

    # --- TAB 3: SCANNER ---
    with tab3:
        st.subheader(f"Full Market Scanner ({len(df)} stocks)")
        st.dataframe(df.sort_values(by=["Vol", "Momentum"], ascending=[False, False]), use_container_width=True, hide_index=True)

    # --- TAB 4: SECTORS ---
    with tab4:
        st.subheader("Sector Performance")
        sel_p = st.select_slider("Timeline", options=list(PERIODS.keys()), value="1Y", key="sec_period")
        col = f"{sel_p} %"

        sec_perf = df.groupby('Sector')[col].mean().reset_index().sort_values(by=col, ascending=False)
        fig = px.bar(sec_perf, x='Sector', y=col, color=col, color_continuous_scale='RdYlGn',
                     color_continuous_midpoint=0, title=f"Sector Avg Return ({sel_p})")
        fig.update_layout(template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("**All timelines at a glance (sector avg %)**")
        heat = df.groupby('Sector')[[f"{p} %" for p in PERIODS]].mean().round(1)
        heat = heat.sort_values(by=col, ascending=False)
        fig_h = px.imshow(heat, color_continuous_scale='RdYlGn', color_continuous_midpoint=0,
                          aspect='auto', text_auto=True)
        fig_h.update_layout(template="plotly_dark", height=max(350, 28 * len(heat) + 100))
        st.plotly_chart(fig_h, use_container_width=True)

        sel = st.selectbox("Drill Down Sector", sec_perf['Sector'].tolist(), key="sec_drill")
        if sel:
            st.dataframe(df[df['Sector'] == sel].sort_values(by=col, ascending=False),
                         use_container_width=True, hide_index=True)

    # --- TAB 5: METALS ---
    with tab5:
        st.subheader("🥇 Metals & Fund Flow")
        metal_data = get_metals("5y")
        if metal_data:
            flow_data = []
            for name, d in metal_data.items():
                rsi = ta.momentum.RSIIndicator(d['Close'], window=14).rsi().iloc[-1]
                status = "🔴 Out" if rsi > 70 else ("🟢 In" if rsi < 30 else "⚪ Neutral")
                row = {"Metal": name, "Price": round(float(d['Close'].iloc[-1]), 2)}
                for p, days in PERIODS.items():
                    row[f"{p} %"] = round(float(get_ret(d, days)), 1)
                row.update({"RSI": round(float(rsi), 1), "Fund Flow": status})
                flow_data.append(row)
            st.dataframe(pd.DataFrame(flow_data), use_container_width=True, hide_index=True)

            m_p = st.select_slider("Chart timeline", options=list(PERIODS.keys()), value="1Y", key="metal_period")
            n = PERIODS[m_p]
            fig_m = go.Figure()
            for name, d in metal_data.items():
                w = d['Close'].tail(n + 1)
                fig_m.add_trace(go.Scatter(x=w.index, y=(w / w.iloc[0]) * 100, mode='lines', name=name))
            fig_m.update_layout(title=f"Metals ({m_p} trend, rebased to 100)", template="plotly_dark", height=380)
            st.plotly_chart(fig_m, use_container_width=True)
        else:
            st.warning("Metals data unavailable right now.")

    # --- TAB 6: BUY/SELL ---
    with tab6:
        st.subheader("📈 Actionable Signals & Hold Times")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("📤 Send 3-Day Top 10 Report"):
                top10 = df.sort_values(by="Momentum", ascending=False).head(10)
                msg = "<b>🚨 3-Day Market Report</b>\n\n<b>🏆 Top 10 Momentum Stocks</b>\n"
                for _, r in top10.iterrows(): msg += f"• {r['Stock']} (Score: {r['Momentum']}) - ₹{r['Price']}\n"
                success, err = send_telegram_message(tg_token, tg_chat_id, msg)
                if success: st.success("✅ 3-Day Report sent!")
                else: st.error(f"❌ Error: {err}")

        with col2:
            if st.button("📅 Send Weekly Update"):
                top10 = df.sort_values(by="1M %", ascending=False).head(10)
                msg = "<b>📅 Weekly Top Performers (1M Return)</b>\n\n"
                for _, r in top10.iterrows(): msg += f"• {r['Stock']}: {r['1M %']}% (₹{r['Price']})\n"
                success, err = send_telegram_message(tg_token, tg_chat_id, msg)
                if success: st.success("✅ Weekly Report sent!")
                else: st.error(f"❌ Error: {err}")

        st.markdown("---")

        if st.button("🔄 Generate Buy/Sell Alerts"):
            with st.spinner("Analyzing all stocks..."):
                sig_list = []
                p_data = st.session_state.p_data

                for stock in df['Stock'].tolist():
                    df_h = p_data.get(stock)
                    if df_h is None or len(df_h) < 30: continue

                    rsi = ta.momentum.RSIIndicator(df_h['Close'], window=14).rsi().iloc[-1]
                    macd = ta.trend.MACD(df_h['Close'])
                    ml, ms = macd.macd().iloc[-1], macd.macd_signal().iloc[-1]

                    stock_row = df[df['Stock'] == stock].iloc[0]
                    mom_score = stock_row['Momentum']

                    if rsi < 40 and ml > ms:
                        typ, why = "STRONG BUY", "RSI low & MACD up."
                        hold = "1-2 Months" if mom_score > 15 else "2-3 Weeks"
                    elif rsi < 40:
                        typ, why = "WEAK BUY", "RSI low."
                        hold = "Wait for MACD"
                    elif rsi > 60 and ml < ms:
                        typ, why = "STRONG SELL", "RSI high & MACD down."
                        hold = "Exit Now"
                    elif rsi > 60:
                        typ, why = "WEAK SELL", "RSI high."
                        hold = "Book Partial Profit"
                    else:
                        continue

                    # Impact = RSI extremity + |momentum| + volume-spike bonus
                    impact = abs(rsi - 50) + abs(mom_score) * 0.5 + (10 if stock_row['Vol'] == "🚨 SPIKE" else 0)

                    sig_list.append({
                        "Stock": stock,
                        "Price": round(float(df_h['Close'].iloc[-1]), 2),
                        "RSI": round(float(rsi), 1),
                        "Type": typ,
                        "Action": f"{SIGNAL_EMOJI[typ]} {typ}",
                        "Hold Time": hold,
                        "Impact": round(float(impact), 1),
                        "Why?": why
                    })

                if sig_list:
                    st.session_state.sig_df = (pd.DataFrame(sig_list)
                        .assign(_o=lambda d: d["Type"].map({k: i for i, k in enumerate(SIGNAL_ORDER)}))
                        .sort_values(["_o", "Impact"], ascending=[True, False]).drop(columns=["_o", "Type"]))
                    success, err = send_telegram_message(tg_token, tg_chat_id, build_alert_message(sig_list, tg_cap))
                    if success: st.success("✅ Buy/Sell Alerts sent to Telegram!")
                    else: st.error(f"❌ Telegram Error: {err}")
                else:
                    st.info("Neutral market. No signals generated.")

        if 'sig_df' in st.session_state:
            st.dataframe(st.session_state.sig_df, use_container_width=True, hide_index=True)
