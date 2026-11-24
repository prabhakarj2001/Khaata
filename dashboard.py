import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
import requests
import io
from nselib import capital_market
import ta
from plotly.subplots import make_subplots

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
        return (True, "Success") if response.status_code == 200 else (False, response.json().get('description', 'Error'))
    except Exception as e: return False, str(e)

# ==========================================
# --- PATTERN DETECTORS ---
# ==========================================
def detect_pattern(row):
    try:
        o, h, l, c = row['Open'], row['High'], row['Low'], row['Close']
        body = abs(c - o); upper_wick = h - max(o, c); lower_wick = min(o, c) - l
        total_range = h - l
        if total_range == 0: return "None"
        if body <= (total_range * 0.1): return "Doji"
        if lower_wick > (2 * body) and upper_wick < body: return "Hammer (Bullish)"
        if upper_wick > (2 * body) and lower_wick < body: return "Shooting Star (Bearish)"
        return "Normal"
    except: return "None"

def detect_engulfing(df):
    if len(df) < 2: return "None"
    prev, curr = df.iloc[-2], df.iloc[-1]
    if prev['Close'] < prev['Open'] and curr['Close'] > curr['Open']:
        if curr['Close'] > prev['Open'] and curr['Open'] < prev['Close']: return "Bullish Engulfing"
    if prev['Close'] > prev['Open'] and curr['Close'] < curr['Open']:
        if curr['Close'] < prev['Open'] and curr['Open'] > prev['Close']: return "Bearish Engulfing"
    return "Normal"

# ==========================================
# --- SIDEBAR CONTROLS ---
# ==========================================
st.sidebar.header("Scanner Settings")
scan_size = st.sidebar.selectbox("How many stocks to scan?", ["Nifty 50 (Fast)", "Nifty 100", "Nifty 500 (Slow)"], index=1)
market_cap_filter = st.sidebar.selectbox("Filter by Market Cap", ["All Stocks", "Large Cap (>50k Cr)", "Mid Cap (18k-50k Cr)", "Small Cap (<18k Cr)"], index=0)

st.sidebar.header("📱 Telegram Alerts")
tg_token = st.sidebar.text_input("Bot Token", type="password", value="9015179938:AAFATXEjxrMZUwPp4csuQO6vmFdae3dBXWE")
tg_chat_id = st.sidebar.text_input("Chat ID", value="1063631401")

# ==========================================
# --- DATA FETCHING ---
# ==========================================
@st.cache_data(ttl=86400)
def get_nse_data():
    try:
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        df = pd.read_csv(io.StringIO(response.text))
        return df['Symbol'].tolist(), dict(zip(df['Symbol'], df['Industry']))
    except: return ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"], {s: "Unknown" for s in ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"]}

@st.cache_data(ttl=86400)
def get_stock_metadata(symbols, nse_sector_map):
    meta = {}
    for sym in symbols:
        sector = nse_sector_map.get(sym.replace(".NS", ""), "Other")
        try:
            ticker = yf.Ticker(sym if sym.endswith(".NS") else sym + ".NS")
            try: mcap = ticker.fast_info['market_cap']
            except: mcap = ticker.info.get('marketCap', 0)
            mcap_cr = mcap / 10000000 if mcap else 0
            try:
                info = ticker.info
                pe, debt = info.get('trailingPE', None), info.get('debtToEquity', None)
            except: pe, debt = None, None
            meta[sym] = {"Sector": sector, "MarketCap_Cr": mcap_cr, "PE": round(pe, 1) if pe else None, "Debt/Equity": round(debt, 1) if debt else None}
        except: meta[sym] = {"Sector": sector, "MarketCap_Cr": 0, "PE": None, "Debt/Equity": None}
    return meta

@st.cache_data(ttl=3600)
def get_fii_dii_data():
    try:
        df = capital_market.fii_dii_trading_activity()
        df = df.rename(columns={'date': 'Date', 'fii_net': 'FII Net (₹ Cr)', 'dii_net': 'DII Net (₹ Cr)'})
        if 'FII Net (₹ Cr)' in df.columns: df['FII Net (₹ Cr)'] = pd.to_numeric(df['FII Net (₹ Cr)'], errors='coerce')
        if 'DII Net (₹ Cr)' in df.columns: df['DII Net (₹ Cr)'] = pd.to_numeric(df['DII Net (₹ Cr)'], errors='coerce')
        return df.tail(7)
    except: return pd.DataFrame()

@st.cache_data(ttl=3600)
def download_price_data(symbols, period="1y"):
    tickers = " ".join([s if s.endswith(".NS") else s + ".NS" for s in symbols])
    return yf.download(tickers, period=period, interval="1d", group_by='ticker', progress=False)

# ==========================================
# --- MAIN APP LOGIC ---
# ==========================================
if st.button("🚀 Fetch Data & Build Dashboard"):
    all_symbols, nse_sector_map = get_nse_data()
    if scan_size == "Nifty 50 (Fast)": target_symbols = all_symbols[:50]
    elif scan_size == "Nifty 100": target_symbols = all_symbols[:100]
    else: target_symbols = all_symbols

    with st.spinner(f"Downloading Data for {len(target_symbols)} stocks..."):
        price_data = download_price_data(target_symbols, period="1y")
        meta_map = get_stock_metadata(target_symbols, nse_sector_map)
        
        results = []
        for symbol in target_symbols:
            try:
                ticker_key = symbol if symbol.endswith(".NS") else symbol + ".NS"
                df = price_data if len(target_symbols) == 1 else price_data[ticker_key]
                df = df.dropna()
                if len(df) < 50: continue

                current_price = df['Close'].iloc[-1]
                meta = meta_map.get(symbol, {})
                mcap_cr = meta.get("MarketCap_Cr", 0)

                if market_cap_filter == "Large Cap (>50k Cr)" and mcap_cr < 50000: continue
                if market_cap_filter == "Mid Cap (18k-50k Cr)" and (mcap_cr < 18000 or mcap_cr > 50000): continue
                if market_cap_filter == "Small Cap (<18k Cr)" and mcap_cr > 18000: continue

                daily_ret = df['Close'].pct_change().mean() * 100
                monthly_ret = ((current_price - df['Close'].iloc[-21]) / df['Close'].iloc[-21]) * 100 if len(df) > 21 else 0
                yearly_ret = ((current_price - df['Close'].iloc[-252]) / df['Close'].iloc[-252]) * 100 if len(df) > 252 else 0
                momentum_score = (daily_ret * 0.2) + (monthly_ret * 0.3) + (yearly_ret * 0.5)

                final_pattern = detect_pattern(df.iloc[-1]) if detect_pattern(df.iloc[-1]) != "Normal" else detect_engulfing(df)
                sma_50 = df['Close'].rolling(50).mean().iloc[-1]
                trend = "🟢 Up" if current_price > sma_50 else "🔴 Down"
                volume_spike = "🚨 SPIKE" if df['Volume'].iloc[-1] > (2 * df['Volume'].rolling(20).mean().iloc[-1]) else "Normal"

                results.append({
                    "Stock": symbol.replace(".NS", ""), "Sector": meta.get("Sector", "Other"),
                    "MCap (Cr)": round(mcap_cr, 0), "P/E": meta.get("PE"), "Debt/Eq": meta.get("Debt/Equity"),
                    "Price": round(float(current_price), 2), "Daily %": round(float(daily_ret), 2), 
                    "Monthly %": round(float(monthly_ret), 1), "Yearly %": round(float(yearly_ret), 1),
                    "Momentum": round(float(momentum_score), 1), "Trend": trend, "Pattern": final_pattern, "Volume": volume_spike
                })
            except: continue 
        st.session_state.df_results = pd.DataFrame(results)

# ==========================================
# --- RENDER TABS ---
# ==========================================
if 'df_results' in st.session_state and not st.session_state.df_results.empty:
    df_results = st.session_state.df_results
    
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "🏆 Top 10 Momentum", "📊 Scanner", "🏢 Sectors", "🏦 FII/DII", "🥇 Metals & Fund Flow", "📈 Buy/Sell", "📉 Sensex"
    ])

    with tab1:
        st.subheader("🏆 Top 10 Performers (Composite Momentum)")
        st.write("Score combines Daily, Monthly, and Yearly returns.")
        top_10 = df_results.sort_values(by="Momentum", ascending=False).head(10)
        st.dataframe(top_10[["Stock", "Sector", "Price", "Daily %", "Monthly %", "Yearly %", "Momentum", "Trend"]], use_container_width=True, hide_index=True)

    with tab2:
        st.subheader(f"Full Scanner ({len(df_results)} stocks)")
        st.dataframe(df_results.sort_values(by=["Volume", "Momentum"], ascending=[False, False]), use_container_width=True, hide_index=True)

    with tab3:
        st.subheader("Sector Performance")
        sector_perf = df_results.groupby('Sector')['Yearly %'].mean().reset_index().sort_values(by='Yearly %', ascending=False)
        fig_sector = px.bar(sector_perf, x='Sector', y='Yearly %', color='Yearly %', color_continuous_scale='RdYlGn')
        fig_sector.update_layout(template="plotly_dark")
        st.plotly_chart(fig_sector, use_container_width=True)
        sel_sector = st.selectbox("Drill Down Sector", sector_perf['Sector'].tolist())
        if sel_sector: st.dataframe(df_results[df_results['Sector'] == sel_sector], use_container_width=True, hide_index=True)

    with tab4:
        st.subheader("FII / DII Flows (Last 7 Days)")
        fii_dii_df = get_fii_dii_data()
        if not fii_dii_df.empty:
            st.dataframe(fii_dii_df, use_container_width=True, hide_index=True)

    with tab5:
        st.subheader("🥇 Metals Performance & Fund Flow")
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
                    status = "🔴 Overbought (Money Out)" if rsi > 70 else ("🟢 Oversold (Money In)" if rsi < 30 else "⚪ Neutral")
                    flow_data.append({"Metal": name, "RSI": round(rsi, 1), "Fund Flow": status})
            except: pass
            
        if metal_data:
            st.markdown("### Money Flow Analysis (RSI-Based)")
            st.dataframe(pd.DataFrame(flow_data), use_container_width=True, hide_index=True)
            
            st.markdown("---")
            st.markdown("### Metal Price Comparison")
            normalized_df = pd.DataFrame({name: (df_m['Close'] / df_m['Close'].iloc[0]) * 100 for name, df_m in metal_data.items()})
            fig_metal = go.Figure()
            for col in normalized_df.columns:
                fig_metal.add_trace(go.Scatter(x=normalized_df.index, y=normalized_df[col], mode='lines', name=col))
            fig_metal.update_layout(title="Metals (2-Year Trend)", template="plotly_dark", height=400)
            st.plotly_chart(fig_metal, use_container_width=True)

    with tab6:
        st.subheader("📈 Actionable Signals & Automated Alert Test")
        
        if st.button("📤 Send 3-Day Top 10 & Metals Report to Telegram"):
            with st.spinner("Sending Report..."):
                top_10 = df_results.sort_values(by="Momentum", ascending=False).head(10)
                msg = "<b>🚨 3-Day Market Report</b>\n\n<b>🏆 Top 10 Momentum Stocks</b>\n"
                for _, row in top_10.iterrows():
                    msg += f"• {row['Stock']} (Score: {row['Momentum']}) - ₹{row['Price']}\n"
                
                msg += "\n<b>🥇 Metals Fund Flow</b>\n"
                for item in flow_data:
                    msg += f"• {item['Metal']}: {item['Fund Flow']} (RSI: {item['RSI']})\n"
                
                success, err = send_telegram_message(tg_token, tg_chat_id, msg)
                if success: st.success("✅ 3-Day Report sent to Telegram!")
                else: st.error(f"❌ Error: {err}")

        st.markdown("---")
        st.subheader("Individual Stock Buy/Sell")
        
        if st.button("🔄 Generate Buy/Sell Alerts"):
            with st.spinner("Analyzing RSI and MACD for all stocks..."):
                signal_list = []
                tg_msg = "<b>🚨 Daily Buy/Sell Alerts</b>\n\n"
                
                # --- BULK DOWNLOAD FIX ---
                stock_list = df_results['Stock'].tolist()
                tickers = [s + ".NS" for s in stock_list]
                
                # Download 3 months of data for ALL stocks in one single request
                bulk_data = yf.download(tickers, period="3mo", interval="1d", group_by='ticker', progress=False)
                
                for stock in stock_list:
                    try:
                        ticker_key = stock + ".NS"
                        # Extract individual stock from the bulk data
                        if isinstance(bulk_data.columns, pd.MultiIndex):
                            if ticker_key in bulk_data.columns.levels[0]:
                                df_hist = bulk_data[ticker_key]
                            else:
                                continue
                        else:
                            df_hist = bulk_data # If only 1 stock
                            
                        df_hist = df_hist.dropna()
                        if len(df_hist) < 30: continue
                        
                        rsi = ta.momentum.RSIIndicator(df_hist['Close'], window=14).rsi().iloc[-1]
                        macd_obj = ta.trend.MACD(df_hist['Close'])
                        macd_line, macd_signal = macd_obj.macd().iloc[-1], macd_obj.macd_signal().iloc[-1]
                        price = df_hist['Close'].iloc[-1]
                        
                        if rsi < 40 and macd_line > macd_signal: signal, reason = "🟢 STRONG BUY", "RSI low & MACD up."
                        elif rsi < 40: signal, reason = "🟡 WEAK BUY", "RSI low."
                        elif rsi > 60 and macd_line < macd_signal: signal, reason = "🔴 STRONG SELL", "RSI high & MACD down."
                        elif rsi > 60: signal, reason = "🟠 WEAK SELL", "RSI high."
                        else: continue
                        
                        signal_list.append({"Stock": stock, "Price": round(price, 2), "RSI": round(rsi, 1), "Action": signal, "Why?": reason})
                        tg_msg += f"<b>{stock}</b>: {signal}\n"
                    except: continue
                
                if signal_list:
                    st.session_state.signal_df = pd.DataFrame(signal_list)
                    send_telegram_message(tg_token, tg_chat_id, tg_msg)
                else: st.info("Neutral market. No signals.")

        if 'signal_df' in st.session_state and not st.session_state.signal_df.empty:
            st.dataframe(st.session_state.signal_df, use_container_width=True, hide_index=True)

    with tab7:
        st.subheader("📉 S&P BSE SENSEX Performance")
        sensex_df = yf.download("^BSESN", period="1y", interval="1d", progress=False)
        if not sensex_df.empty:
            if isinstance(sensex_df.columns, pd.MultiIndex): sensex_df.columns = sensex_df.columns.get_level_values(0)
            sensex_df = sensex_df.dropna()
            fig_sensex = go.Figure(data=[go.Candlestick(x=sensex_df.index, open=sensex_df['Open'], high=sensex_df['High'], low=sensex_df['Low'], close=sensex_df['Close'])])
            fig_sensex.update_layout(template="plotly_dark", xaxis_rangeslider_visible=False, height=400)
            st.plotly_chart(fig_sensex, use_container_width=True)
            
        st.markdown("""
        <div style="background-color:#2a1a1a; padding:15px; border-radius:10px; border-left:5px solid #FF4B4B; margin-top: 20px;">
            <h4 style="color:#FF4B4B;">⚠️ Macro-Economic 'Look Out'</h4>
            <ul style="color:#E0E0E0;">
                <li><b>RBI Rates:</b> Hikes contract markets, cuts expand them.</li>
                <li><b>FII Selling:</b> Heavy outflows drag Nifty down.</li>
                <li><b>Oil Prices:</b> Spikes hurt India's import bill.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
