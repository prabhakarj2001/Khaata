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
# --- TELEGRAM ALERT FUNCTION (WITH ERROR LOGGING) ---
# ==========================================
def send_telegram_message(token, chat_id, message):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            return True, "Success"
        else:
            # Return the exact error from Telegram (e.g., "chat not found")
            return False, response.json().get('description', 'Unknown error')
    except Exception as e:
        return False, str(e)

# ==========================================
# --- PATTERN DETECTORS ---
# ==========================================
def detect_pattern(row):
    try:
        o, h, l, c = row['Open'], row['High'], row['Low'], row['Close']
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
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
# --- TOP ANALYSIS OVERVIEW BOARD ---
# ==========================================
st.markdown("""
<div style="background-color:#1E1E1E; padding:15px; border-radius:10px; border-left:5px solid #00FFAA; margin-bottom:20px;">
    <h4 style="color:#00FFAA; margin-top:0;">🔍 Available Analyses</h4>
    <ul style="color:#E0E0E0; margin-bottom:0;">
        <li><b>Sensex & Macro:</b> Multi-period chart and Macro warnings.</li>
        <li><b>Stock Scanner:</b> Momentum, Candlestick Patterns, P/E, Debt/Equity.</li>
        <li><b>Sector & Metals:</b> Industry performance and Commodity tracking.</li>
        <li><b>Institutional Flow:</b> FII/DII Net Buying/Selling.</li>
        <li><b>Actionable Signals:</b> RSI/MACD scanner + Telegram Bot alerts.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# ==========================================
# --- SIDEBAR CONTROLS ---
# ==========================================
st.sidebar.header("Scanner Settings")
scan_size = st.sidebar.selectbox("How many stocks to scan?", ["Nifty 50 (Fast)", "Nifty 100", "Nifty 500 (Slow)"], index=1)
market_cap_filter = st.sidebar.selectbox("Filter by Market Cap", ["All Stocks", "Large Cap (>50k Cr)", "Mid Cap (18k-50k Cr)", "Small Cap (<18k Cr)"], index=0)

st.sidebar.header("📱 Telegram Alerts Setup")
tg_token = st.sidebar.text_input("Telegram Bot Token", type="password")
tg_chat_id = st.sidebar.text_input("Telegram Chat ID")

# ==========================================
# --- DATA FETCHING FUNCTIONS ---
# ==========================================
@st.cache_data(ttl=86400)
def get_nse_data():
    try:
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        df = pd.read_csv(io.StringIO(response.text))
        return df['Symbol'].tolist(), dict(zip(df['Symbol'], df['Industry']))
    except:
        fallback = ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "SBIN"]
        return fallback, {sym: "Unknown" for sym in fallback}

@st.cache_data(ttl=86400)
def get_stock_metadata(symbols, nse_sector_map):
    meta = {}
    for sym in symbols:
        sector = nse_sector_map.get(sym.replace(".NS", ""), "Other")
        try:
            ticker = yf.Ticker(sym if sym.endswith(".NS") else sym + ".NS")
            # Try fast_info first (less rate limited), fallback to info
            try:
                mcap = ticker.fast_info['market_cap']
            except:
                mcap = ticker.info.get('marketCap', 0)
            
            mcap_cr = mcap / 10000000 if mcap else 0
            
            try:
                info = ticker.info
                pe = info.get('trailingPE', None)
                debt = info.get('debtToEquity', None)
            except:
                pe, debt = None, None
                
            meta[sym] = {"Sector": sector, "MarketCap_Cr": mcap_cr, "PE": round(pe, 1) if pe else None, "Debt/Equity": round(debt, 1) if debt else None}
        except:
            meta[sym] = {"Sector": sector, "MarketCap_Cr": 0, "PE": None, "Debt/Equity": None}
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
def download_price_data(symbols, period="5y"):
    tickers = " ".join([s if s.endswith(".NS") else s + ".NS" for s in symbols])
    return yf.download(tickers, period=period, interval="1d", group_by='ticker', progress=False)

# ==========================================
# --- MAIN APP LOGIC ---
# ==========================================
if st.button("🚀 Fetch Data & Build Dashboard"):
    all_symbols, nse_sector_map = get_nse_data()
    small_cap_etfs = ["HDFCSML250.NS", "MOSMALL250.NS"]
    
    if scan_size == "Nifty 50 (Fast)": target_symbols = list(set(all_symbols[:50] + small_cap_etfs))
    elif scan_size == "Nifty 100": target_symbols = list(set(all_symbols[:100] + small_cap_etfs))
    else: target_symbols = list(set(all_symbols + small_cap_etfs))

    with st.spinner(f"Downloading Data & Fundamentals for {len(target_symbols)} stocks..."):
        price_data = download_price_data(target_symbols, period="5y")
        meta_map = get_stock_metadata(target_symbols, nse_sector_map)
        
        results = []
        for symbol in target_symbols:
            try:
                ticker_key = symbol if symbol.endswith(".NS") else symbol + ".NS"
                if len(target_symbols) == 1: df = price_data
                else: df = price_data[ticker_key]
                df = df.dropna()
                if len(df) < 50: continue

                current_price = df['Close'].iloc[-1]
                meta = meta_map.get(symbol, {})
                mcap_cr = meta.get("MarketCap_Cr", 0)

                if market_cap_filter == "Large Cap (>50k Cr)" and mcap_cr < 50000: continue
                if market_cap_filter == "Mid Cap (18k-50k Cr)" and (mcap_cr < 18000 or mcap_cr > 50000): continue
                if market_cap_filter == "Small Cap (<18k Cr)" and mcap_cr > 18000: continue

                ret_1m = ((current_price - df['Close'].iloc[-21]) / df['Close'].iloc[-21]) * 100 if len(df) > 21 else 0
                ret_1y = ((current_price - df['Close'].iloc[-252]) / df['Close'].iloc[-252]) * 100 if len(df) > 252 else 0
                
                final_pattern = detect_pattern(df.iloc[-1]) if detect_pattern(df.iloc[-1]) != "Normal" else detect_engulfing(df)

                sma_50 = df['Close'].rolling(50).mean().iloc[-1]
                trend = "🟢 Up" if current_price > sma_50 else "🔴 Down"
                volume_spike = "🚨 SPIKE" if df['Volume'].iloc[-1] > (2 * df['Volume'].rolling(20).mean().iloc[-1]) else "Normal"

                results.append({
                    "Stock": symbol.replace(".NS", ""),
                    "Sector": meta.get("Sector", "Other"),
                    "MCap (Cr)": round(mcap_cr, 0),
                    "P/E": meta.get("PE"),
                    "Debt/Eq": meta.get("Debt/Equity"),
                    "Price": round(float(current_price), 2),
                    "1M %": round(float(ret_1m), 1),
                    "1Y %": round(float(ret_1y), 1),
                    "Trend": trend,
                    "Pattern": final_pattern,
                    "Volume": volume_spike
                })
            except:
                continue 
        st.session_state.df_results = pd.DataFrame(results)

# ==========================================
# --- RENDER DASHBOARD TABS ---
# ==========================================
if 'df_results' in st.session_state and not st.session_state.df_results.empty:
    df_results = st.session_state.df_results
    
    # ALL 7 TABS RESTORED
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📉 Sensex & Macro", "📊 Stock Scanner", "🏢 Sector Analysis", 
        "🏦 Institutional Flow", "🥇 Metals", "📈 Actionable Buy/Sell"
    ])

    # --- TAB 1: SENSEX & MACRO ---
    with tab1:
        st.subheader("📉 S&P BSE SENSEX Performance")
        sensex_df = yf.download("^BSESN", period="5y", interval="1d", progress=False)
        if not sensex_df.empty:
            if isinstance(sensex_df.columns, pd.MultiIndex): sensex_df.columns = sensex_df.columns.get_level_values(0)
            sensex_df = sensex_df.dropna()
            
            fig_sensex = go.Figure(data=[go.Candlestick(x=sensex_df.index, open=sensex_df['Open'], high=sensex_df['High'], low=sensex_df['Low'], close=sensex_df['Close'])])
            fig_sensex.update_layout(template="plotly_dark", xaxis_rangeslider_visible=False, height=400, title="Sensex 5-Year Chart")
            st.plotly_chart(fig_sensex, use_container_width=True)
            
        st.markdown("---")
        st.subheader("⚠️ Macro-Economic 'Look Out' (Booms & Busts)")
        st.markdown("""
        <div style="background-color:#2a1a1a; padding:15px; border-radius:10px; border-left:5px solid #FF4B4B;">
            <h4 style="color:#FF4B4B; margin-top:0;">What to watch out for before buying:</h4>
            <ul style="color:#E0E0E0;">
                <li><b>Interest Rates (RBI):</b> If RBI increases rates, borrowing becomes expensive. Markets usually fall. If rates are cut, markets boom.</li>
                <li><b>FII Flows (Foreign Money):</b> Check the FII tab. If foreigners are selling heavily for weeks, the market will drop.</li>
                <li><b>Global Geopolitics:</b> Wars or US-China tensions cause oil prices to spike. High oil = bad for India.</li>
                <li><b>Election Cycles:</b> 3-6 months before major elections, markets are highly volatile.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

    # --- TAB 2: STOCK SCANNER ---
    with tab2:
        st.subheader(f"Stock Performance (Found {len(df_results)} stocks)")
        st.dataframe(
            df_results.sort_values(by=["Volume", "Trend"], ascending=[False, True])[["Stock", "Sector", "MCap (Cr)", "P/E", "Debt/Eq", "Price", "1M %", "1Y %", "Trend", "Pattern", "Volume"]],
            use_container_width=True, hide_index=True
        )

    # --- TAB 3: SECTOR ANALYSIS ---
    with tab3:
        st.subheader("🏆 Sector Performance (Past 1 Year)")
        sector_perf = df_results.groupby('Sector')['1Y %'].mean().reset_index()
        sector_perf = sector_perf.sort_values(by='1Y %', ascending=False)
        fig_sector = px.bar(sector_perf, x='Sector', y='1Y %', color='1Y %', color_continuous_scale='RdYlGn', title="Average 1-Year Return by Sector (%)")
        fig_sector.update_layout(template="plotly_dark")
        st.plotly_chart(fig_sector, use_container_width=True)
        
        st.markdown("---")
        selected_sector = st.selectbox("Drill Down: Select a Sector", sector_perf['Sector'].tolist())
        if selected_sector:
            sector_stocks = df_results[df_results['Sector'] == selected_sector].sort_values(by="1Y %", ascending=False)
            st.dataframe(sector_stocks[["Stock", "MCap (Cr)", "1M %", "1Y %", "Trend", "Pattern"]], use_container_width=True, hide_index=True)

    # --- TAB 4: INSTITUTIONAL FLOW ---
    with tab4:
        st.subheader("🏦 FII/DII Activity (Last 7 Days)")
        fii_dii_df = get_fii_dii_data()
        if not fii_dii_df.empty:
            st.dataframe(fii_dii_df, use_container_width=True, hide_index=True)
            date_col = 'Date' if 'Date' in fii_dii_df.columns else fii_dii_df.index
            if 'FII Net (₹ Cr)' in fii_dii_df.columns:
                fig_flow = go.Figure()
                fig_flow.add_trace(go.Bar(x=date_col, y=fii_dii_df['FII Net (₹ Cr)'], name='FII Net', marker_color='orange'))
                if 'DII Net (₹ Cr)' in fii_dii_df.columns:
                    fig_flow.add_trace(go.Bar(x=date_col, y=fii_dii_df['DII Net (₹ Cr)'], name='DII Net', marker_color='cyan'))
                fig_flow.update_layout(barmode='group', template='plotly_dark')
                st.plotly_chart(fig_flow, use_container_width=True)
        else:
            st.warning("Could not load FII/DII data right now.")

    # --- TAB 5: METALS ---
    with tab5:
        st.subheader("🥇 Metal Comparison")
        metals = {'Gold': 'GC=F', 'Silver': 'SI=F', 'Copper': 'HG=F', 'Platinum': 'PL=F', 'Palladium': 'PA=F'}
        metal_df = pd.DataFrame()
        for name, ticker in metals.items():
            try:
                df_m = yf.download(ticker, period="10y", interval="1d", progress=False)
                if not df_m.empty:
                    if isinstance(df_m.columns, pd.MultiIndex): metal_df[name] = df_m['Close'].iloc[:, 0]
                    else: metal_df[name] = df_m['Close']
            except: pass
            
        if not metal_df.empty:
            normalized_df = (metal_df / metal_df.iloc[0]) * 100
            metal_time = st.select_slider("Select Metal Timeframe", options=["1M", "6M", "1Y", "3Y", "5Y", "10Y"], value="5Y")
            days_map = {"1M": 21, "6M": 126, "1Y": 252, "3Y": 756, "5Y": 1260, "10Y": 2520}
            plot_metals = normalized_df.tail(days_map[metal_time]) if len(normalized_df) > days_map[metal_time] else normalized_df
            
            fig_metal = go.Figure()
            for col in plot_metals.columns:
                fig_metal.add_trace(go.Scatter(x=plot_metals.index, y=plot_metals[col], mode='lines', name=col))
            fig_metal.update_layout(title=f"Metal Performance ({metal_time})", template="plotly_dark", height=500)
            st.plotly_chart(fig_metal, use_container_width=True)
        else:
            st.warning("Could not load metal data.")

    # --- TAB 6: BUY/SELL & TELEGRAM ---
    with tab6:
        st.subheader("📈 Actionable Buy/Sell Signals")
        
        if st.button("🔄 Generate & Send Alerts"):
            with st.spinner("Analyzing RSI and MACD..."):
                signal_list = []
                tg_msg = "<b>🚨 Daily Stock Scanner Alerts</b>\n\n"
                
                for stock in df_results['Stock'].tolist():
                    try:
                        df_hist = yf.download(stock + ".NS", period="3mo", interval="1d", progress=False)
                        if isinstance(df_hist.columns, pd.MultiIndex): df_hist.columns = df_hist.columns.get_level_values(0)
                        df_hist = df_hist.dropna()
                        if len(df_hist) < 30: continue
                        
                        rsi = ta.momentum.RSIIndicator(df_hist['Close'], window=14).rsi().iloc[-1]
                        macd_obj = ta.trend.MACD(df_hist['Close'])
                        macd_line, macd_signal = macd_obj.macd().iloc[-1], macd_obj.macd_signal().iloc[-1]
                        price = df_hist['Close'].iloc[-1]
                        
                        if rsi < 40 and macd_line > macd_signal:
                            signal, reason = "🟢 BUY", "RSI low, MACD crossed up."
                        elif rsi > 65 and macd_line < macd_signal:
                            signal, reason = "🔴 SELL", "RSI high, MACD crossed down."
                        else: continue
                            
                        signal_list.append({"Stock": stock, "Price": round(price, 2), "RSI": round(rsi, 1), "Action": signal, "Why?": reason})
                        tg_msg += f"<b>{stock}</b>: {signal} at ₹{round(price, 2)}\n<i>{reason}</i>\n\n"
                    except: continue
                
                if signal_list:
                    st.session_state.signal_df = pd.DataFrame(signal_list)
                    if tg_token and tg_chat_id:
                        success, err_msg = send_telegram_message(tg_token, tg_chat_id, tg_msg)
                        if success: st.success("✅ Alerts sent to your Telegram!")
                        else: st.error(f"❌ Telegram Error: {err_msg}") # Will show exact error
                else:
                    st.session_state.signal_df = pd.DataFrame()
                    st.info("No strong setups found.")

        if 'signal_df' in st.session_state and not st.session_state.signal_df.empty:
            st.dataframe(st.session_state.signal_df, use_container_width=True, hide_index=True)
