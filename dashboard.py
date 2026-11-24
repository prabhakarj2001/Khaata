import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
import requests
import io
import time
import ta

st.set_page_config(page_title="Market Master Scanner", layout="wide")
st.title("📈 Ultimate Market & Sector Scanner")

# ==========================================
# --- TELEGRAM FUNCTION ---
# ==========================================
def send_telegram_message(token, chat_id, message):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        response = requests.post(url, json=payload)
        return response.status_code == 200, response.json().get('description', 'Error')
    except Exception as e: return False, str(e)

# ==========================================
# --- SIDEBAR CONTROLS ---
# ==========================================
st.sidebar.header("Scanner Settings")
scan_size = st.sidebar.selectbox("Stocks to scan?", ["Nifty 50 (Fast)", "Nifty 100", "Nifty 500 (Slow)"], index=1)
mcap_filter = st.sidebar.selectbox("Market Cap Filter", ["All Stocks", "Large Cap (>50k Cr)", "Mid Cap (18k-50k Cr)", "Small Cap (<18k Cr)"], index=0)

st.sidebar.header("📱 Telegram Alerts")
tg_token = st.sidebar.text_input("Bot Token", type="password", value="9015179938:AAFATXEjxrMZUwPp4csuQO6vmFdae3dBXWE")
tg_chat_id = st.sidebar.text_input("Chat ID", value="1063631401")

# ==========================================
# --- DATA FETCHING & CALCULATIONS ---
# ==========================================
@st.cache_data(ttl=86400)
def get_nse_data():
    try:
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        df = pd.read_csv(io.StringIO(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10).text))
        return df['Symbol'].tolist(), dict(zip(df['Symbol'], df['Industry']))
    except: return ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"], {s: "Unknown" for s in ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"]}

@st.cache_data(ttl=86400)
def get_metadata(symbols, nse_map):
    meta = {}
    for sym in symbols:
        sector = nse_map.get(sym.replace(".NS", ""), "Other")
        try:
            ticker = yf.Ticker(sym if sym.endswith(".NS") else sym + ".NS")
            try: mcap = ticker.fast_info['market_cap']
            except: mcap = ticker.info.get('marketCap', 0)
            try: pe = ticker.info.get('trailingPE', None)
            except: pe = None
            meta[sym] = {"Sector": sector, "MCap": mcap / 10000000 if mcap else 0, "PE": round(pe, 1) if pe else None}
        except: meta[sym] = {"Sector": sector, "MCap": 0, "PE": None}
    return meta

def get_ret(df, days):
    if len(df) > days: return ((df['Close'].iloc[-1] - df['Close'].iloc[-days]) / df['Close'].iloc[-days]) * 100
    return 0.0

@st.cache_data(ttl=3600)
def download_data(symbols, period="5y"):
    all_data = {}
    for i in range(0, len(symbols), 25): # Chunking
        chunk = symbols[i:i+25]
        tickers = [s if s.endswith(".NS") else s + ".NS" for s in chunk]
        data = yf.download(tickers, period=period, interval="1d", group_by='ticker', progress=False)
        if not data.empty:
            for s in chunk:
                tk = s if s.endswith(".NS") else s + ".NS"
                if isinstance(data.columns, pd.MultiIndex) and tk in data.columns.levels[0]:
                    all_data[s] = data[tk].dropna()
                elif not isinstance(data.columns, pd.MultiIndex) and len(chunk) == 1:
                    all_data[s] = data.dropna()
        time.sleep(1.2) # Prevent rate limit
    return all_data

# ==========================================
# --- MAIN LOGIC ---
# ==========================================
if st.button("🚀 Fetch Data & Build Dashboard"):
    all_syms, nse_map = get_nse_data()
    target_syms = all_syms[:50] if scan_size == "Nifty 50 (Fast)" else (all_syms[:100] if scan_size == "Nifty 100" else all_syms)

    with st.spinner(f"Downloading 5-Year Data for {len(target_syms)} stocks..."):
        p_data = download_data(target_syms, period="5y")
        m_map = get_metadata(target_syms, nse_map)
        
        results = []
        for sym in target_syms:
            df = p_data.get(sym)
            if df is None or len(df) < 50: continue
            
            mcap = m_map.get(sym, {}).get("MCap", 0)
            if mcap_filter == "Large Cap (>50k Cr)" and mcap < 50000: continue
            if mcap_filter == "Mid Cap (18k-50k Cr)" and (mcap < 18000 or mcap > 50000): continue
            if mcap_filter == "Small Cap (<18k Cr)" and mcap > 18000: continue

            price = df['Close'].iloc[-1]
            r_1m = get_ret(df, 21)
            r_3m = get_ret(df, 63)
            r_6m = get_ret(df, 126)
            r_1y = get_ret(df, 252)
            r_3y = get_ret(df, 756)
            r_5y = get_ret(df, 1260)
            
            mom = (r_1m * 0.2) + (r_6m * 0.3) + (r_1y * 0.5)
            trend = "🟢 Up" if price > df['Close'].rolling(50).mean().iloc[-1] else "🔴 Down"
            vol_spike = "🚨 SPIKE" if df['Volume'].iloc[-1] > (2 * df['Volume'].rolling(20).mean().iloc[-1]) else "Normal"

            results.append({
                "Stock": sym.replace(".NS", ""), "Sector": m_map.get(sym, {}).get("Sector", "Other"),
                "MCap (Cr)": round(mcap, 0), "P/E": m_map.get(sym, {}).get("PE"), "Price": round(float(price), 2),
                "1M %": round(float(r_1m), 1), "3M %": round(float(r_3m), 1), "6M %": round(float(r_6m), 1),
                "1Y %": round(float(r_1y), 1), "3Y %": round(float(r_3y), 1), "5Y %": round(float(r_5y), 1),
                "Momentum": round(float(mom), 1), "Trend": trend, "Vol": vol_spike
            })
        st.session_state.df = pd.DataFrame(results)
        st.session_state.p_data = p_data # Saved for Buy/Sell tab

# ==========================================
# --- RENDER TABS ---
# ==========================================
if 'df' in st.session_state and not st.session_state.df.empty:
    df = st.session_state.df
    
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "🏆 Top 10", "📊 Scanner", "🏢 Sectors", "🥇 Metals", "📈 Buy/Sell", "📉 Sensex"
    ])

    with tab1:
        st.subheader("🏆 Top 10 Multi-Period Performers")
        top10 = df.sort_values(by="Momentum", ascending=False).head(10)
        st.dataframe(top10[["Stock", "Sector", "Price", "1M %", "6M %", "1Y %", "3Y %", "5Y %", "Momentum"]], use_container_width=True, hide_index=True)

    with tab2:
        st.subheader(f"Full Market Scanner ({len(df)} stocks)")
        st.dataframe(df.sort_values(by=["Vol", "Momentum"], ascending=[False, False]), use_container_width=True, hide_index=True)

    with tab3:
        st.subheader("Sector Performance (1Y Avg)")
        sec_perf = df.groupby('Sector')['1Y %'].mean().reset_index().sort_values(by='1Y %', ascending=False)
        fig = px.bar(sec_perf, x='Sector', y='1Y %', color='1Y %', color_continuous_scale='RdYlGn')
        fig.update_layout(template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
        sel = st.selectbox("Drill Down Sector", sec_perf['Sector'].tolist())
        if sel: st.dataframe(df[df['Sector'] == sel], use_container_width=True, hide_index=True)

    with tab4:
        st.subheader("🥇 Metals & Fund Flow")
        metals = {'Gold': 'GC=F', 'Silver': 'SI=F', 'Copper': 'HG=F', 'Platinum': 'PL=F', 'Palladium': 'PA=F'}
        metal_data, flow_data = {}, []
        for name, ticker in metals.items():
            try:
                df_m = yf.download(ticker, period="2y", interval="1d", progress=False)
                if not df_m.empty:
                    if isinstance(df_m.columns, pd.MultiIndex): df_m.columns = df_m.columns.get_level_values(0)
                    df_m = df_m.dropna()
                    metal_data[name] = df_m
                    rsi = ta.momentum.RSIIndicator(df_m['Close'], window=14).rsi().iloc[-1]
                    status = "🔴 Out" if rsi > 70 else ("🟢 In" if rsi < 30 else "⚪ Neutral")
                    flow_data.append({"Metal": name, "RSI": round(rsi, 1), "Fund Flow": status})
            except: pass
        if metal_data:
            st.dataframe(pd.DataFrame(flow_data), use_container_width=True, hide_index=True)
            norm_df = pd.DataFrame({n: (d['Close']/d['Close'].iloc[0])*100 for n, d in metal_data.items()})
            fig_m = go.Figure([go.Scatter(x=norm_df.index, y=norm_df[c], mode='lines', name=c) for c in norm_df.columns])
            fig_m.update_layout(title="Metals (2-Year Trend)", template="plotly_dark", height=350)
            st.plotly_chart(fig_m, use_container_width=True)

    with tab5:
        st.subheader("📈 Actionable Signals")
        
        if st.button("📤 Send 3-Day Top 10 Report"):
            top10 = df.sort_values(by="Momentum", ascending=False).head(10)
            msg = "<b>🚨 3-Day Market Report</b>\n\n<b>🏆 Top 10 Momentum Stocks</b>\n"
            for _, r in top10.iterrows(): msg += f"• {r['Stock']} (Score: {r['Momentum']}) - ₹{r['Price']}\n"
            msg += "\n<b>🥇 Metals</b>\n" + "\n".join([f"• {i['Metal']}: {i['Fund Flow']} (RSI: {i['RSI']})" for i in flow_data])
            success, err = send_telegram_message(tg_token, tg_chat_id, msg)
            if success: st.success("✅ Report sent!")
            else: st.error(f"❌ Error: {err}")

        st.markdown("---")
        if st.button("🔄 Generate Buy/Sell Alerts"):
            with st.spinner("Analyzing all stocks..."):
                sig_list, tg_msg = [], "<b>🚨 Buy/Sell Alerts</b>\n\n"
                p_data = st.session_state.p_data
                
                for stock in df['Stock'].tolist():
                    df_h = p_data.get(stock)
                    if df_h is None or len(df_h) < 30: continue
                    rsi = ta.momentum.RSIIndicator(df_h['Close'], window=14).rsi().iloc[-1]
                    macd = ta.trend.MACD(df_h['Close'])
                    ml, ms = macd.macd().iloc[-1], macd.macd_signal().iloc[-1]
                    
                    if rsi < 40 and ml > ms: sig, why = "🟢 STRONG BUY", "RSI low & MACD up."
                    elif rsi < 40: sig, why = "🟡 WEAK BUY", "RSI low."
                    elif rsi > 60 and ml < ms: sig, why = "🔴 STRONG SELL", "RSI high & MACD down."
                    elif rsi > 60: sig, why = "🟠 WEAK SELL", "RSI high."
                    else: continue
                    
                    sig_list.append({"Stock": stock, "Price": round(df_h['Close'].iloc[-1], 2), "RSI": round(rsi, 1), "Action": sig, "Why?": why})
                    tg_msg += f"<b>{stock}</b>: {sig}\n"
                    
                if sig_list:
                    st.session_state.sig_df = pd.DataFrame(sig_list)
                    send_telegram_message(tg_token, tg_chat_id, tg_msg)
                else: st.info("Neutral market.")
        
        if 'sig_df' in st.session_state:
            st.dataframe(st.session_state.sig_df, use_container_width=True, hide_index=True)

    with tab6:
        st.subheader("📉 Sensex Performance")
        s_df = yf.download("^BSESN", period="1y", interval="1d", progress=False)
        if not s_df.empty:
            if isinstance(s_df.columns, pd.MultiIndex): s_df.columns = s_df.columns.get_level_values(0)
            fig_s = go.Figure(data=[go.Candlestick(x=s_df.dropna().index, open=s_df['Open'], high=s_df['High'], low=s_df['Low'], close=s_df['Close'])])
            fig_s.update_layout(template="plotly_dark", xaxis_rangeslider_visible=False, height=350)
            st.plotly_chart(fig_s, use_container_width=True)
