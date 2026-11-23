import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
import requests
import io
from nselib import capital_market

st.set_page_config(page_title="Market Master Scanner", layout="wide")
st.title("📈 Ultimate Market & Sector Scanner")

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

# --- SIDEBAR CONTROLS ---
st.sidebar.header("Scanner Settings")
scan_size = st.sidebar.selectbox("How many stocks to scan?", ["Nifty 50 (Fast)", "Nifty 100", "Nifty 500 (Slow)"], index=1)

market_cap_filter = st.sidebar.selectbox(
    "Filter by Market Cap",
    ["All Stocks", "Large Cap (>50k Cr)", "Mid Cap (18k-50k Cr)", "Small Cap (<18k Cr)"],
    index=0
)

# --- 1. DYNAMICALLY FETCH STOCK LIST ---
@st.cache_data(ttl=86400)
def get_nifty_symbols():
    try:
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))
        symbols = df['Symbol'].tolist()
        if len(symbols) > 400:
            return symbols
    except:
        pass

    fallback = [
        "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "SBIN", "BHARTIARTL", "ITC", "LT", "KOTAKBANK",
        "AXISBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI", "TATASTEEL", "SUNPHARMA", "TITAN", "ULTRACEMCO",
        "WIPRO", "NESTLEIND", "POWERGRID", "NTPC", "TECHM", "HCLTECH", "ADANIENT", "ADANIPORTS", "APOLLOHOSP",
        "ASIANPAINT", "BAJAJ-AUTO", "BEL", "BPCL", "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB",
        "DRREDDY", "EICHERMOT", "GRASIM", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "ICICIGI", "ICICIPRULI",
        "INDUSINDBK", "JSWSTEEL", "LTIM", "LTTS", "M&M", "ONGC", "PIDILITIND", "SBILIFE", "SHRIRAMFIN", 
        "TATACHEM", "TATACONSUM", "TATAMOTORS", "TATAPOWER", "ZOMATO", "PAYTM", "NYKAA", "POLICYBZR", 
        "DMART", "IRCTC", "IRFC", "RVNL", "HUDCO", "BHEL", "HAL", "MAZDOCK", "COCHINSHIP", "BDL", 
        "SOLARINDS", "SUZLON", "YESBANK", "IDEA", "PNB", "BANKBARODA", "CANBK", "UNIONBANK", "IOB", 
        "CENTRALBK", "VEDL", "NMDC", "SAIL", "JINDALSTEL", "HINDZINC", "NATIONALUM", "HINDCOPPER", 
        "DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "LODHA", "PHOENIXLTD", "MUTHOOTFIN", "CHOLAFIN", 
        "BAJAJFINSV", "ABFRL", "TRENT", "VBL", "UBL", "MCDOWELL-N", "PGHH", "DABUR", "GODREJCP", "MARICO", 
        "COLPAL", "PIIND", "UPL", "SRF", "BALKRISIND", "MRF", "MOTHERSON", "BOSCHLTD", "APOLLOTYRE",
        "ESDS", "POLYCAB", "KPITTECH", "CGPOWER"
    ]
    return list(set(fallback))

# --- 2. FETCH SECTOR & MARKET CAP DATA ---
@st.cache_data(ttl=86400)
def get_stock_metadata(symbols):
    meta = {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym if sym.endswith(".NS") else sym + ".NS")
            info = ticker.info
            mcap = info.get('marketCap', 0)
            mcap_cr = mcap / 10000000 if mcap else 0
            meta[sym] = {
                "Sector": info.get('sector', 'Other'),
                "Industry": info.get('industry', 'Other'),
                "MarketCap_Cr": mcap_cr
            }
        except:
            meta[sym] = {"Sector": "Other", "Industry": "Other", "MarketCap_Cr": 0}
    return meta

# --- 3. FETCH FII/DII DATA ---
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

# --- 4. DOWNLOAD PRICE DATA ---
@st.cache_data(ttl=3600)
def download_price_data(symbols, period="3y"):
    tickers = " ".join([s if s.endswith(".NS") else s + ".NS" for s in symbols])
    data = yf.download(tickers, period=period, interval="1d", group_by='ticker', progress=False)
    return data

# --- MAIN LOGIC ---
if st.button("🚀 Fetch Data & Build Dashboard"):
    all_symbols = get_nifty_symbols()
    small_cap_etfs = ["HDFCSML250.NS", "MOSMALL250.NS"]
    
    if scan_size == "Nifty 50 (Fast)": target_symbols = list(set(all_symbols[:50] + small_cap_etfs))
    elif scan_size == "Nifty 100": target_symbols = list(set(all_symbols[:100] + small_cap_etfs))
    else: target_symbols = list(set(all_symbols + small_cap_etfs))

    with st.spinner(f"Downloading 3-Year Data for {len(target_symbols)} stocks. Please wait..."):
        price_data = download_price_data(target_symbols, period="3y")
        meta_map = get_stock_metadata(target_symbols)
        
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

                ret_1m = ((current_price - df['Close'].iloc[-21]) / df['Close'].iloc[-21]) * 100 if len(df) > 21 else 0
                price_1y_ago = df['Close'].iloc[-252] if len(df) > 252 else df['Close'].iloc[0]
                ret_1y = ((current_price - price_1y_ago) / price_1y_ago) * 100
                price_3y_ago = df['Close'].iloc[0]
                ret_3y = ((current_price - price_3y_ago) / price_3y_ago) * 100

                sma_50 = df['Close'].rolling(50).mean().iloc[-1]
                trend = "🟢 Up" if current_price > sma_50 else "🔴 Down"

                avg_volume = df['Volume'].rolling(20).mean().iloc[-1]
                latest_volume = df['Volume'].iloc[-1]
                volume_spike = "🚨 SPIKE" if latest_volume > (2 * avg_volume) else "Normal"

                results.append({
                    "Stock": symbol.replace(".NS", ""),
                    "Sector": meta_map.get(symbol, {}).get("Sector", "Other"),
                    "Industry": meta_map.get(symbol, {}).get("Industry", "Other"), 
                    "MCap (Cr)": round(mcap_cr, 0),
                    "Price": round(float(current_price), 2),
                    "1M Ret %": round(float(ret_1m), 1),
                    "1Y Ret %": round(float(ret_1y), 1),
                    "3Y Ret %": round(float(ret_3y), 1),
                    "Trend": trend,
                    "Volume Signal": volume_spike
                })
            except:
                continue 

        st.session_state.df_results = pd.DataFrame(results)

# ==========================================
# RENDER DASHBOARD
# ==========================================
if 'df_results' in st.session_state and not st.session_state.df_results.empty:
    df_results = st.session_state.df_results
    
    tab1, tab2, tab3 = st.tabs(["📊 Stock Scanner", "🏢 Sector Analysis", "🏦 Institutional Flow (FII/DII)"])

    # --- TAB 1: STOCK SCANNER ---
    with tab1:
        st.subheader(f"Stock Performance (Found {len(df_results)} stocks)")
        df_sorted = df_results.sort_values(by=["Volume Signal", "1Y Ret %"], ascending=[False, False])
        
        st.dataframe(
            df_sorted[["Stock", "Sector", "MCap (Cr)", "Price", "1M Ret %", "1Y Ret %", "3Y Ret %", "Trend", "Volume Signal"]], 
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
                
                fig = go.Figure(data=[go.Candlestick(
                    x=chart_data.index, open=chart_data['Open'], high=chart_data['High'],
                    low=chart_data['Low'], close=chart_data['Close']
                )])
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

    # --- TAB 2: SECTOR ANALYSIS ---
    with tab2:
        st.subheader("🏆 Sector Performance (Past 3 Years)")
        sector_perf = df_results.groupby('Sector')['3Y Ret %'].mean().reset_index()
        sector_perf = sector_perf.sort_values(by='3Y Ret %', ascending=False)

        fig_sector = px.bar(
            sector_perf, x='Sector', y='3Y Ret %', 
            color='3Y Ret %', color_continuous_scale='RdYlGn',
            title="Average 3-Year Return by Sector (%)"
        )
        fig_sector.update_layout(template="plotly_dark")
        st.plotly_chart(fig_sector, use_container_width=True)

        st.markdown("---")
        st.subheader("🔍 Drill Down: Stocks inside a Sector")
        selected_sector = st.selectbox("Select a Sector:", sector_perf['Sector'].tolist())
        
        if selected_sector:
            sector_stocks = df_results[df_results['Sector'] == selected_sector]
            sector_stocks = sector_stocks.sort_values(by="3Y Ret %", ascending=False)
            st.write(f"Showing stocks in the **{selected_sector}** sector:")
            st.dataframe(sector_stocks[["Stock", "Industry", "MCap (Cr)", "1Y Ret %", "3Y Ret %", "Trend"]], use_container_width=True, hide_index=True)

    # --- TAB 3: INSTITUTIONAL FLOW ---
    with tab3:
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
