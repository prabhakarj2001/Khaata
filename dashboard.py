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
# --- TOP ANALYSIS OVERVIEW BOARD ---
# ==========================================
st.markdown("""
<div style="background-color:#1E1E1E; padding:15px; border-radius:10px; border-left:5px solid #00FFAA; margin-bottom:20px;">
    <h4 style="color:#00FFAA; margin-top:0;">🔍 Available Analyses</h4>
    <ul style="color:#E0E0E0; margin-bottom:0;">
        <li><b>Sensex Overview:</b> Multi-period performance & interactive timeline slider.</li>
        <li><b>Stock Scanner:</b> Momentum, Volume Spikes, & Multi-Period Returns (1M, 6M, 1Y, 3Y, 5Y).</li>
        <li><b>Sector Analysis:</b> Average 3-Year Sector Returns & Drill-Down (Now uses exact NSE data).</li>
        <li><b>Institutional Flow:</b> FII/DII Net Buying/Selling (Last 7 Days).</li>
        <li><b>Metal Comparison:</b> Compare Gold, Silver, Copper, Platinum, Palladium with a timeline slider.</li>
        <li><b>Buy/Sell Signals:</b> Interactive RSI & MACD charts with real-time Buy/Sell recommendations.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# ==========================================
# --- RETRACTABLE HISTORICAL NEWS TAB ---
# ==========================================
with st.expander("🚨 Click here to view Top 10 Historical News Events That Moved the Market"):
    news_events = [
        {"Event Date": "June 4, 2024", "Event": "Election Result Day (Coalition Shock)", "Impact": "Sensex -5.7% (Single Day)"},
        {"Event Date": "Jan 25-27, 2023", "Event": "Adani-Hindenburg Report Released", "Impact": "Sensex -1.45% (2-Session)"},
        {"Event Date": "Mar 23, 2020", "Event": "COVID-19 Nationwide Lockdown", "Impact": "Sensex -13.15% (Single Day)"},
        {"Event Date": "Sep 14-28, 2018", "Event": "IL&FS Liquidity Crisis Default", "Impact": "Sensex -4.89% (2-Week)"},
        {"Event Date": "Nov 8-9, 2016", "Event": "Demonetisation Announcement", "Impact": "Sensex -6.12% (Intraday)"},
        {"Event Date": "Sep 20, 2019", "Event": "Corporate Tax Rate Cut", "Impact": "Massive Rally (Positive)"},
        {"Event Date": "May 16, 2014", "Event": "General Election Mandate (NDA Win)", "Impact": "Intra-day Record High"},
        {"Event Date": "Apr 29, 1992", "Event": "Harshad Mehta Scam Exposed", "Impact": "Sensex -12.77% (Single Day)"},
        {"Event Date": "May 18, 2004", "Event": "Unexpected Election Result Shock", "Impact": "Market Crashed (Lower Circuit)"},
        {"Event Date": "Oct 2008", "Event": "Global Financial Crisis (Lehman Brothers)", "Impact": "Sensex -50% (Over 6 Months)"},
    ]
    df_news = pd.DataFrame(news_events)
    st.dataframe(df_news, use_container_width=True, hide_index=True)
    st.info("💡 Understanding historical market crashes helps gauge sentiment during current volatility.")

# ==========================================
# --- SIDEBAR CONTROLS ---
# ==========================================
st.sidebar.header("Scanner Settings")
scan_size = st.sidebar.selectbox("How many stocks to scan?", ["Nifty 50 (Fast)", "Nifty 100", "Nifty 500 (Slow)"], index=1)

market_cap_filter = st.sidebar.selectbox(
    "Filter by Market Cap",
    ["All Stocks", "Large Cap (>50k Cr)", "Mid Cap (18k-50k Cr)", "Small Cap (<18k Cr)"],
    index=0
)

# ==========================================
# --- CACHED DATA FETCHING FUNCTIONS ---
# ==========================================
@st.cache_data(ttl=86400)
def get_nse_data():
    """Fetches the official Nifty 500 list and extracts exact Industry/Sector data."""
    try:
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))
        symbols = df['Symbol'].tolist()
        # Map Symbol to Industry (which serves as the Sector)
        sector_map = dict(zip(df['Symbol'], df['Industry']))
        return symbols, sector_map
    except:
        # Fallback if NSE blocks
        fallback = ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "SBIN", "BHARTIARTL", "ITC", "LT", "KOTAKBANK", "AXISBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI"]
        return fallback, {sym: "Unknown" for sym in fallback}

@st.cache_data(ttl=86400)
def get_stock_metadata(symbols, nse_sector_map):
    """Fetches Market Cap from Yahoo Finance, and uses NSE map for Sector."""
    meta = {}
    for sym in symbols:
        sector = nse_sector_map.get(sym.replace(".NS", ""), "Other")
        try:
            ticker = yf.Ticker(sym if sym.endswith(".NS") else sym + ".NS")
            info = ticker.info
            mcap = info.get('marketCap', 0)
            mcap_cr = mcap / 10000000 if mcap else 0
            meta[sym] = {"Sector": sector, "MarketCap_Cr": mcap_cr}
        except:
            meta[sym] = {"Sector": sector, "MarketCap_Cr": 0}
    return meta

@st.cache_data(ttl=3600)
def get_fii_dii_data():
    try:
        df = capital_market.fii_dii_trading_activity()
        df = df.rename(columns={'date': 'Date', 'fii_net': 'FII Net (₹ Cr)', 'dii_net': 'DII Net (₹ Cr)'})
        if 'FII Net (₹ Cr)' in df.columns: df['FII Net (₹ Cr)'] = pd.to_numeric(df['FII Net (₹ Cr)'], errors='coerce')
        if 'DII Net (₹ Cr)' in df.columns: df['DII Net (₹ Cr)'] = pd.to_numeric(df['DII Net (₹ Cr)'], errors='coerce')
        return df.tail(7)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def download_price_data(symbols, period="5y"):
    tickers = " ".join([s if s.endswith(".NS") else s + ".NS" for s in symbols])
    data = yf.download(tickers, period=period, interval="1d", group_by='ticker', progress=False)
    return data

# ==========================================
# --- MAIN APP LOGIC & TABS ---
# ==========================================
if st.button("🚀 Fetch Data & Build Dashboard"):
    all_symbols, nse_sector_map = get_nse_data()
    small_cap_etfs = ["HDFCSML250.NS", "MOSMALL250.NS"]
    
    if scan_size == "Nifty 50 (Fast)": target_symbols = list(set(all_symbols[:50] + small_cap_etfs))
    elif scan_size == "Nifty 100": target_symbols = list(set(all_symbols[:100] + small_cap_etfs))
    else: target_symbols = list(set(all_symbols + small_cap_etfs))

    with st.spinner(f"Downloading 5-Year Data for {len(target_symbols)} stocks. Please wait..."):
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
                mcap_cr = meta_map.get(symbol, {}).get("MarketCap_Cr", 0)

                if market_cap_filter == "Large Cap (>50k Cr)" and mcap_cr < 50000: continue
                if market_cap_filter == "Mid Cap (18k-50k Cr)" and (mcap_cr < 18000 or mcap_cr > 50000): continue
                if market_cap_filter == "Small Cap (<18k Cr)" and mcap_cr > 18000: continue

                # Calculate Returns
                ret_1m = ((current_price - df['Close'].iloc[-21]) / df['Close'].iloc[-21]) * 100 if len(df) > 21 else 0
                ret_6m = ((current_price - df['Close'].iloc[-126]) / df['Close'].iloc[-126]) * 100 if len(df) > 126 else 0
                ret_1y = ((current_price - df['Close'].iloc[-252]) / df['Close'].iloc[-252]) * 100 if len(df) > 252 else 0
                price_3y_ago = df['Close'].iloc[-756] if len(df) > 756 else df['Close'].iloc[0]
                ret_3y = ((current_price - price_3y_ago) / price_3y_ago) * 100
                price_5y_ago = df['Close'].iloc[0]
                ret_5y = ((current_price - price_5y_ago) / price_5y_ago) * 100

                sma_50 = df['Close'].rolling(50).mean().iloc[-1]
                trend = "🟢 Up" if current_price > sma_50 else "🔴 Down"

                avg_volume = df['Volume'].rolling(20).mean().iloc[-1]
                latest_volume = df['Volume'].iloc[-1]
                volume_spike = "🚨 SPIKE" if latest_volume > (2 * avg_volume) else "Normal"

                results.append({
                    "Stock": symbol.replace(".NS", ""),
                    "Sector": meta_map.get(symbol, {}).get("Sector", "Other"),
                    "MCap (Cr)": round(mcap_cr, 0),
                    "Price": round(float(current_price), 2),
                    "1M Ret %": round(float(ret_1m), 1),
                    "6M Ret %": round(float(ret_6m), 1),
                    "1Y Ret %": round(float(ret_1y), 1),
                    "3Y Ret %": round(float(ret_3y), 1),
                    "5Y Ret %": round(float(ret_5y), 1),
                    "Trend": trend,
                    "Volume Signal": volume_spike
                })
            except:
                continue 
        st.session_state.df_results = pd.DataFrame(results)

# ==========================================
# --- RENDER DASHBOARD TABS ---
# ==========================================
if 'df_results' in st.session_state and not st.session_state.df_results.empty:
    df_results = st.session_state.df_results
    
    # TAB 1 is now Sensex Overview
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📉 Sensex Overview", "📊 Stock Scanner", "🏢 Sector Analysis", 
        "🏦 Institutional Flow", "🥇 Metal Comparison", "📈 Buy/Sell Signals"
    ])

    # --- TAB 1: SENSEX OVERVIEW (NEW SLIDER) ---
    with tab1:
        st.subheader("📉 S&P BSE SENSEX Performance")
        
        @st.cache_data(ttl=3600)
        def get_sensex_data():
            try:
                return yf.download("^BSESN", period="5y", interval="1d", progress=False)
            except:
                return pd.DataFrame()
        
        sensex_df = get_sensex_data()
        
        if not sensex_df.empty:
            if isinstance(sensex_df.columns, pd.MultiIndex):
                sensex_df.columns = sensex_df.columns.get_level_values(0)
            sensex_df = sensex_df.dropna()
            
            sensex_price = sensex_df['Close'].iloc[-1]
            periods = {'1M': 21, '6M': 126, '1Y': 252, '3Y': 756, '5Y': 1260}
            
            # Returns Table
            sensex_returns = []
            for p_name, p_days in periods.items():
                if len(sensex_df) > p_days:
                    ret = ((sensex_price - sensex_df['Close'].iloc[-p_days]) / sensex_df['Close'].iloc[-p_days]) * 100
                    sensex_returns.append({'Period': p_name, 'Return (%)': round(float(ret), 1)})
                else:
                    sensex_returns.append({'Period': p_name, 'Return (%)': None})
            
            st.subheader("📊 Multi-Period Returns")
            st.dataframe(pd.DataFrame(sensex_returns), use_container_width=True, hide_index=True)
            
            # Chart Slider
            st.subheader("📈 Sensex Chart")
            selected_period = st.select_slider("Select Timeframe", options=["1M", "6M", "1Y", "3Y", "5Y"], value="1Y")
            days_to_show = periods[selected_period]
            plot_df = sensex_df.tail(days_to_show) if len(sensex_df) > days_to_show else sensex_df
            
            fig_sensex = go.Figure(data=[go.Candlestick(x=plot_df.index, open=plot_df['Open'], high=plot_df['High'], low=plot_df['Low'], close=plot_df['Close'], name="Sensex")])
            fig_sensex.update_layout(template="plotly_dark", xaxis_rangeslider_visible=False, height=500, title=f"Sensex - {selected_period} Chart")
            st.plotly_chart(fig_sensex, use_container_width=True)
        else:
            st.warning("Could not load Sensex data.")

    # --- TAB 2: STOCK SCANNER ---
    with tab2:
        st.subheader(f"Stock Performance (Found {len(df_results)} stocks)")
        df_sorted = df_results.sort_values(by=["Volume Signal", "1Y Ret %"], ascending=[False, False])
        
        st.dataframe(
            df_sorted[["Stock", "Sector", "MCap (Cr)", "Price", "1M Ret %", "6M Ret %", "1Y Ret %", "3Y Ret %", "5Y Ret %", "Trend", "Volume Signal"]],
            use_container_width=True, hide_index=True
        )

        st.markdown("---")
        col_chart, col_news = st.columns([2, 1])
        with col_chart:
            st.subheader("📉 Candlestick Chart")
            selected_stock = st.selectbox("Select a stock to view chart:", df_sorted['Stock'].tolist())
            if selected_stock:
                chart_data = yf.download(selected_stock + ".NS", period="1y", interval="1d", progress=False)
                if isinstance(chart_data.columns, pd.MultiIndex):
                    chart_data.columns = chart_data.columns.get_level_values(0)
                chart_data = chart_data.dropna()
                fig = go.Figure(data=[go.Candlestick(x=chart_data.index, open=chart_data['Open'], high=chart_data['High'], low=chart_data['Low'], close=chart_data['Close'])])
                fig.update_layout(title=f"{selected_stock} - 1 Year Chart", xaxis_rangeslider_visible=False, template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
        with col_news:
            st.subheader(f"📰 Latest News")
            if selected_stock:
                try:
                    ticker_info = yf.Ticker(selected_stock + ".NS")
                    news = ticker_info.news
                    if not news:
                        st.info("No recent news found for this stock.")
                    else:
                        for article in news[:5]:
                            title = article.get('title', 'No Title')
                            link = article.get('link', '#')
                            publisher = article.get('publisher', 'Unknown')
                            pub_time = article.get('providerPublishTime', None)
                            time_str = pd.to_datetime(pub_time, unit='s').strftime('%b %d, %H:%M') if pub_time else "Recent"
                            st.markdown(f"**[{title}]({link})**")
                            st.caption(f"Source: {publisher} | {time_str}")
                            st.markdown("---")
                except Exception as e:
                    st.warning("Could not load live news at this time.")

    # --- TAB 3: SECTOR ANALYSIS ---
    with tab3:
        st.subheader("🏆 Sector Performance (Past 3 Years)")
        sector_perf = df_results.groupby('Sector')['3Y Ret %'].mean().reset_index()
        sector_perf = sector_perf.sort_values(by='3Y Ret %', ascending=False)
        fig_sector = px.bar(sector_perf, x='Sector', y='3Y Ret %', color='3Y Ret %', color_continuous_scale='RdYlGn', title="Average 3-Year Return by Sector (%)")
        fig_sector.update_layout(template="plotly_dark")
        st.plotly_chart(fig_sector, use_container_width=True)
        st.markdown("---")
        st.subheader("🔍 Drill Down: Stocks inside a Sector")
        selected_sector = st.selectbox("Select a Sector:", sector_perf['Sector'].tolist())
        if selected_sector:
            sector_stocks = df_results[df_results['Sector'] == selected_sector]
            sector_stocks = sector_stocks.sort_values(by="3Y Ret %", ascending=False)
            st.write(f"Showing stocks in the **{selected_sector}** sector:")
            st.dataframe(sector_stocks[["Stock", "MCap (Cr)", "1Y Ret %", "3Y Ret %", "5Y Ret %", "Trend"]], use_container_width=True, hide_index=True)

    # --- TAB 4: INSTITUTIONAL FLOW ---
    with tab4:
        st.subheader("🏦 Foreign & Domestic Institutional Activity (Last 7 Days)")
        st.write("Positive numbers mean **buying**, negative means **selling**.")
        fii_dii_df = get_fii_dii_data()
        if not fii_dii_df.empty:
            st.dataframe(fii_dii_df, use_container_width=True, hide_index=True)
            date_col = 'Date' if 'Date' in fii_dii_df.columns else fii_dii_df.index
            if 'FII Net (₹ Cr)' in fii_dii_df.columns:
                fig_flow = go.Figure()
                fig_flow.add_trace(go.Bar(x=date_col, y=fii_dii_df['FII Net (₹ Cr)'], name='FII Net', marker_color='orange'))
                if 'DII Net (₹ Cr)' in fii_dii_df.columns:
                    fig_flow.add_trace(go.Bar(x=date_col, y=fii_dii_df['DII Net (₹ Cr)'], name='DII Net', marker_color='cyan'))
                fig_flow.update_layout(barmode='group', title="Institutional Net Flow (₹ Cr)", template='plotly_dark')
                st.plotly_chart(fig_flow, use_container_width=True)
        else:
            st.warning("Could not load FII/DII data at this moment. The NSE API might be busy. Please try again in a few minutes.")

    # --- TAB 5: METAL COMPARISON (NEW SLIDER & METALS) ---
    with tab5:
        st.subheader("🥇 Metal Performance Comparison")
        
        # Added Palladium and timeframe slider
        metals = {'Gold': 'GC=F', 'Silver': 'SI=F', 'Copper': 'HG=F', 'Platinum': 'PL=F', 'Palladium': 'PA=F'}
        
        @st.cache_data(ttl=3600)
        def get_metal_data():
            data = {}
            for name, ticker in metals.items():
                try:
                    df = yf.download(ticker, period="10y", interval="1d", progress=False)
                    if not df.empty:
                        if isinstance(df.columns, pd.MultiIndex):
                            data[name] = df['Close'].iloc[:, 0]
                        else:
                            data[name] = df['Close']
                except:
                    pass
            return pd.DataFrame(data)
        
        metal_df = get_metal_data()
        
        if not metal_df.empty:
            # Normalize
            normalized_df = (metal_df / metal_df.iloc[0]) * 100
            
            # Slider for Metals
            metal_time = st.select_slider("Select Metal Timeframe", options=["1M", "6M", "1Y", "3Y", "5Y", "10Y"], value="5Y")
            days_map = {"1M": 21, "6M": 126, "1Y": 252, "3Y": 756, "5Y": 1260, "10Y": 2520}
            plot_metals = normalized_df.tail(days_map[metal_time]) if len(normalized_df) > days_map[metal_time] else normalized_df
            
            fig_metal = go.Figure()
            for col in plot_metals.columns:
                fig_metal.add_trace(go.Scatter(x=plot_metals.index, y=plot_metals[col], mode='lines', name=col))
            
            fig_metal.update_layout(title=f"Metal Performance ({metal_time} - Normalized to 100)", template="plotly_dark", height=500)
            st.plotly_chart(fig_metal, use_container_width=True)
            
            st.subheader("📊 Metal Returns by Period")
            periods = {'1M': 21, '6M': 126, '1Y': 252, '3Y': 756, '5Y': 1260, '10Y': 2520}
            returns_data = []
            for name in metal_df.columns:
                row = {'Metal': name}
                for p_name, p_days in periods.items():
                    if len(metal_df) > p_days:
                        ret = ((metal_df[name].iloc[-1] - metal_df[name].iloc[-p_days]) / metal_df[name].iloc[-p_days]) * 100
                        row[p_name] = round(float(ret), 1)
                    else:
                        row[p_name] = None
                returns_data.append(row)
            st.dataframe(pd.DataFrame(returns_data), use_container_width=True, hide_index=True)
        else:
            st.warning("Could not load metal data.")

    # --- TAB 6: BUY/SELL SIGNALS (NEW RECOMMENDATION) ---
    with tab6:
        st.subheader("📈 Interactive Buy/Sell Signal Chart")
        signal_stock = st.selectbox("Select a stock for signal analysis:", df_results['Stock'].tolist())
        
        col_slider1, col_slider2 = st.columns(2)
        with col_slider1:
            rsi_lower = st.slider("RSI Oversold Level (Buy Signal)", 10, 50, 30)
        with col_slider2:
            rsi_upper = st.slider("RSI Overbought Level (Sell Signal)", 50, 90, 70)
            
        if signal_stock:
            with st.spinner("Calculating indicators..."):
                df_sig = yf.download(signal_stock + ".NS", period="1y", interval="1d", progress=False)
                if isinstance(df_sig.columns, pd.MultiIndex):
                    df_sig.columns = df_sig.columns.get_level_values(0)
                df_sig = df_sig.dropna()
                
                if not df_sig.empty:
                    df_sig['RSI'] = ta.momentum.RSIIndicator(df_sig['Close'], window=14).rsi()
                    macd = ta.trend.MACD(df_sig['Close'])
                    df_sig['MACD'] = macd.macd()
                    df_sig['MACD_Signal'] = macd.macd_signal()
                    
                    # GET LATEST VALUES FOR RECOMMENDATION
                    last_rsi = df_sig['RSI'].iloc[-1]
                    last_macd = df_sig['MACD'].iloc[-1]
                    last_signal = df_sig['MACD_Signal'].iloc[-1]
                    
                    # SHOW RECOMMENDATION
                    if last_rsi < rsi_lower and last_macd > last_signal:
                        st.success(f"🟢 **Recommendation: BUY**. Latest RSI is {last_rsi:.1f} (Oversold) and MACD crossed above the signal line.")
                    elif last_rsi > rsi_upper and last_macd < last_signal:
                        st.error(f"🔴 **Recommendation: SELL**. Latest RSI is {last_rsi:.1f} (Overbought) and MACD crossed below the signal line.")
                    else:
                        st.warning(f"🟡 **Recommendation: WAIT/HOLD**. Latest RSI is {last_rsi:.1f}. No strong convergence between RSI and MACD right now.")

                    fig_sig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.6, 0.2, 0.2])
                    
                    fig_sig.add_trace(go.Candlestick(x=df_sig.index, open=df_sig['Open'], high=df_sig['High'], low=df_sig['Low'], close=df_sig['Close'], name="Price"), row=1, col=1)
                    
                    fig_sig.add_trace(go.Scatter(x=df_sig.index, y=df_sig['RSI'], name="RSI", line=dict(color='purple')), row=2, col=1)
                    fig_sig.add_hline(y=rsi_lower, line_dash="dash", line_color="green", row=2, col=1)
                    fig_sig.add_hline(y=rsi_upper, line_dash="dash", line_color="red", row=2, col=1)
                    
                    fig_sig.add_trace(go.Scatter(x=df_sig.index, y=df_sig['MACD'], name="MACD", line=dict(color='blue')), row=3, col=1)
                    fig_sig.add_trace(go.Scatter(x=df_sig.index, y=df_sig['MACD_Signal'], name="MACD Signal", line=dict(color='orange')), row=3, col=1)
                    
                    fig_sig.update_layout(title=f"{signal_stock} - Buy/Sell Signals", template="plotly_dark", xaxis_rangeslider_visible=False, height=800)
                    st.plotly_chart(fig_sig, use_container_width=True)
                else:
                    st.error("Could not load price data for this stock.")
