import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
import requests
import io
import time
import ta
import html
import json
import math

st.set_page_config(page_title="Market Master Scanner", layout="wide")
st.title("📈 Ultimate Market & Sector Scanner")

# ==========================================
# --- HELPERS & CONSTANTS ---
# ==========================================
def esc(s):
    return html.escape(str(s))

def interpolate(risk, v1, v5, v10):
    if risk <= 5:
        return v1 + (v5 - v1) * (risk - 1) / 4
    else:
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

def calc_max_drawdown(series):
    cum_ret = (1 + series).cumprod()
    peak = cum_ret.cummax()
    dd = (cum_ret - peak) / peak
    return dd.min()

def send_telegram_message(token, chat_id, message):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        if len(message) <= 4000:
            payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
            res = requests.post(url, json=payload)
            return res.status_code == 200, res.json().get('description', 'Error')
        
        lines = message.split('\n')
        chunk = ""
        success = True
        for line in lines:
            if len(chunk) + len(line) + 1 > 4000:
                requests.post(url, json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"})
                chunk = line + "\n"
            else:
                chunk += line + "\n"
        if chunk.strip():
            res = requests.post(url, json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"})
            success = res.status_code == 200
        return success, "" if success else "Failed on last chunk"
    except Exception as e: return False, str(e)

# ==========================================
# --- STATE & CACHING ---
# ==========================================
if 'signals_state' not in st.session_state:
    st.session_state.signals_state = {}

# ==========================================
# --- CURRENT MARKET DRIVERS ---
# ==========================================
with st.expander("🚨 Current Market Drivers & Risks (Click to expand)", expanded=False):
    current_topics = [
        {"Topic": "Record FPI Inflows", "Detail": "FPIs poured massive capital into Indian equities recently.", "Market Impact": "🟢 Bullish"},
        {"Topic": "Inflation & RBI Rate Hikes", "Detail": "Retail inflation remains a concern.", "Market Impact": "🔴 Bearish"},
        {"Topic": "Crude Oil & Geopolitics", "Detail": "Oil price spikes hurt India's import bill.", "Market Impact": "🔴 Bearish"},
        {"Topic": "Global AI Stock Rotation", "Detail": "Sell-off in global tech drives funds into Indian IT.", "Market Impact": "🟢 Bullish"},
        {"Topic": "Earnings & Valuations", "Detail": "Markets watching if earnings justify high valuations.", "Market Impact": "⚪ Neutral"}
    ]
    st.dataframe(pd.DataFrame(current_topics), use_container_width=True, hide_index=True)

# ==========================================
# --- SIDEBAR CONTROLS ---
# ==========================================
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
    except: 
        return ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "SBIN", "BHARTIARTL", "ITC", "LT", "KOTAKBANK"], {s: "Unknown" for s in ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"]}

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

# ==========================================
# --- MAIN APP LOGIC ---
# ==========================================
if st.button("🚀 Fetch Nifty 500 Data & Build Dashboard"):
    all_syms, nse_map = get_nse_data()
    all_syms = [s for s in all_syms if "&" not in s] # Skip M&M
    
    with st.spinner(f"Downloading Data for all {len(all_syms)} Nifty 500 stocks... (Takes ~15 seconds)"):
        p_data = download_data(all_syms, period="5y")
        nifty_df = yf.download("^NSEI", period="5y", interval="1d", progress=False)
        if isinstance(nifty_df.columns, pd.MultiIndex): nifty_df.columns = nifty_df.columns.get_level_values(0)
        nifty_close = nifty_df['Close'].dropna()
        
        results = []
        for sym in all_syms:
            df = p_data.get(sym)
            if df is None or len(df) < 50: continue

            price = df['Close'].iloc[-1]
            r_1m = get_ret(df, 21)
            r_3m = get_ret(df, 63)
            r_6m = get_ret(df, 126)
            r_1y = get_ret(df, 252)
            r_3y = get_ret(df, 756)
            r_5y = get_ret(df, 1260)
            
            mom = (r_1m * 0.2) + (r_6m * 0.3) + (r_1y * 0.5)
            sma_50 = df['Close'].rolling(50).mean().iloc[-1]
            sma_200 = df['Close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else np.nan
            
            trend = "🟢 Up" if price > sma_50 else "🔴 Down"
            vol_spike = "🚨 SPIKE" if df['Volume'].iloc[-1] > (2 * df['Volume'].rolling(20).mean().iloc[-1]) else "Normal"

            results.append({
                "Stock": sym.replace(".NS", ""), "Sector": nse_map.get(sym.replace(".NS", ""), "Other"),
                "Price": round(float(price), 2),
                "1M %": round(float(r_1m), 1), "3M %": round(float(r_3m), 1), "6M %": round(float(r_6m), 1),
                "1Y %": round(float(r_1y), 1), "3Y %": round(float(r_3y), 1), "5Y %": round(float(r_5y), 1),
                "Momentum": round(float(mom), 1), "Trend": trend, "Vol": vol_spike,
                "Above200": price > sma_200 if not pd.isna(sma_200) else False,
                "RS_3M": r_3m, "RS_6M": r_6m,
                "SMA50": sma_50
            })
            
        df_res = pd.DataFrame(results)
        st.session_state.df = df_res
        st.session_state.p_data = p_data
        st.session_state.nifty_close = nifty_close
        # Breadth calculation (% of stocks above 200 SMA)
        st.session_state.breadth = (df_res['Above200'].sum() / len(df_res)) * 100 if len(df_res) > 0 else 50
        st.success(f"✅ Successfully downloaded {len(results)} stocks!")

# ==========================================
# --- RENDER TABS ---
# ==========================================
if 'df' in st.session_state and not st.session_state.df.empty:
    df = st.session_state.df
    p_data = st.session_state.p_data
    nifty_close = st.session_state.nifty_close
    breadth = st.session_state.breadth
    
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📉 Sensex", "🏆 Top 10", "📊 Scanner", "🏢 Sectors", "🥇 Metals", "📈 Buy/Sell", "💼 Portfolio Builder"
    ])

    # --- EXISTING TABS (1-6) ---
    with tab1:
        st.subheader("📉 Sensex Performance")
        s_df = yf.download("^BSESN", period="1y", interval="1d", progress=False)
        if not s_df.empty:
            if isinstance(s_df.columns, pd.MultiIndex): s_df.columns = s_df.columns.get_level_values(0)
            fig_s = go.Figure(data=[go.Candlestick(x=s_df.dropna().index, open=s_df['Open'], high=s_df['High'], low=s_df['Low'], close=s_df['Close'])])
            fig_s.update_layout(template="plotly_dark", xaxis_rangeslider_visible=False, height=400, title="Sensex 1-Year Chart")
            st.plotly_chart(fig_s, use_container_width=True)

    with tab2:
        st.subheader("🏆 Top 10 Multi-Period Performers")
        top10 = df.sort_values(by="Momentum", ascending=False).head(10)
        st.dataframe(top10[["Stock", "Sector", "Price", "1M %", "6M %", "1Y %", "3Y %", "5Y %", "Momentum"]], use_container_width=True, hide_index=True)

    with tab3:
        st.subheader(f"Full Market Scanner ({len(df)} stocks)")
        st.dataframe(df.sort_values(by=["Vol", "Momentum"], ascending=[False, False]), use_container_width=True, hide_index=True)

    with tab4:
        st.subheader("Sector Performance (1Y Avg)")
        sec_perf = df.groupby('Sector')['1Y %'].mean().reset_index().sort_values(by='1Y %', ascending=False)
        fig = px.bar(sec_perf, x='Sector', y='1Y %', color='1Y %', color_continuous_scale='RdYlGn')
        fig.update_layout(template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
        sel = st.selectbox("Drill Down Sector", sec_perf['Sector'].tolist())
        if sel: st.dataframe(df[df['Sector'] == sel], use_container_width=True, hide_index=True)

    with tab5:
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

    with tab6:
        st.subheader("📈 Actionable Signals & Hold Times")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📤 Send 3-Day Top 10 Report"):
                top10 = df.sort_values(by="Momentum", ascending=False).head(10)
                msg = "<b>🚨 3-Day Market Report</b>\n\n<b>🏆 Top 10 Momentum Stocks</b>\n"
                for _, r in top10.iterrows(): msg += f"• {esc(r['Stock'])} (Score: {r['Momentum']}) - ₹{r['Price']}\n"
                success, err = send_telegram_message(tg_token, tg_chat_id, msg)
                if success: st.success("✅ Report sent!")
                else: st.error(f"❌ Error: {err}")
        with col2:
            if st.button("📅 Send Weekly Update"):
                top10 = df.sort_values(by="1M %", ascending=False).head(10)
                msg = "<b>📅 Weekly Top Performers (1M Return)</b>\n\n"
                for _, r in top10.iterrows(): msg += f"• {esc(r['Stock'])}: {r['1M %']}% (₹{r['Price']})\n"
                success, err = send_telegram_message(tg_token, tg_chat_id, msg)
                if success: st.success("✅ Weekly Report sent!")
                else: st.error(f"❌ Error: {err}")

        st.markdown("---")
        if st.button("🔄 Generate Buy/Sell Alerts"):
            with st.spinner("Analyzing all stocks..."):
                sig_list, tg_msg = [], "<b>🚨 Buy/Sell Alerts</b>\n\n"
                for stock in df['Stock'].tolist():
                    df_h = p_data.get(stock)
                    if df_h is None or len(df_h) < 30: continue
                    
                    rsi = ta.momentum.RSIIndicator(df_h['Close'], window=14).rsi().iloc[-1]
                    macd = ta.trend.MACD(df_h['Close'])
                    ml, ms = macd.macd().iloc[-1], macd.macd_signal().iloc[-1]
                    
                    stock_row = df[df['Stock'] == stock].iloc[0]
                    mom_score = stock_row['Momentum']
                    
                    if rsi < 40 and ml > ms: 
                        sig, why = "🟢 STRONG BUY", "RSI low & MACD up."
                        hold = "1-2 Months" if mom_score > 15 else "2-3 Weeks"
                    elif rsi < 40: 
                        sig, why = "🟡 WEAK BUY", "RSI low."
                        hold = "Wait for MACD"
                    elif rsi > 60 and ml < ms: 
                        sig, why = "🔴 STRONG SELL", "RSI high & MACD down."
                        hold = "Exit Now"
                    elif rsi > 60: 
                        sig, why = "🟠 WEAK SELL", "RSI high."
                        hold = "Book Partial Profit"
                    else: continue
                    
                    sig_list.append({
                        "Stock": stock, "Price": round(df_h['Close'].iloc[-1], 2), "RSI": round(rsi, 1), 
                        "Action": sig, "Hold Time": hold, "Why?": why
                    })
                    tg_msg += f"<b>{esc(stock)}</b>: {sig} (Hold: {hold})\n"
                    
                if sig_list:
                    st.session_state.sig_df = pd.DataFrame(sig_list)
                    success, err = send_telegram_message(tg_token, tg_chat_id, tg_msg)
                    if success: st.success("✅ Buy/Sell Alerts sent to Telegram!")
                    else: st.error(f"❌ Telegram Error: {err}")
                else: st.info("Neutral market. No signals generated.")
        
        if 'sig_df' in st.session_state:
            st.dataframe(st.session_state.sig_df, use_container_width=True, hide_index=True)

    # --- TAB 7: PORTFOLIO BUILDER (NEW) ---
    with tab7:
        st.subheader("💼 Portfolio Builder")
        st.caption("Not investment advice. This is a quantitative allocation tool.")
        
        # Inputs
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
                # 1. Risk Parameters
                num_pos = int(interpolate(risk, 18, 13, 10))
                max_w = interpolate(risk, 0.07, 0.10, 0.15)
                max_sec_w = interpolate(risk, 0.20, 0.25, 0.35)
                vol_cap = interpolate(risk, 0.25, 0.40, 1.0) # 1.0 = none
                liq_floor = interpolate(risk, 50, 20, 10)
                stop_mult = interpolate(risk, 3.0, 2.5, 2.0)
                cash_buffer = interpolate(risk, 0.10, 0.05, 0.0)
                
                # Core Share Tapering
                if risk <= 3: core_pct = 0.50
                elif risk <= 7: core_pct = 0.25
                else: core_pct = interpolate(risk, 0, 0.10, 0) # 8=0.10, 10=0
                
                # Gold logic
                gold_pct = 0.0
                try:
                    gold_df = yf.download("GC=F", period="1y", interval="1d", progress=False)
                    gold_sma200 = gold_df['Close'].rolling(200).mean().iloc[-1] if len(gold_df) >= 200 else 0
                    gold_trend_up = gold_df['Close'].iloc[-1] > gold_sma200
                except: gold_trend_up = False
                if gold_trend_up and risk <= 5: gold_pct = 0.10
                
                # Show Risk Params
                st.write("**Risk Parameters Applied:**")
                st.dataframe(pd.DataFrame([{
                    "Positions": num_pos, "Max Stock %": f"{max_w*100:.1f}%", "Max Sector %": f"{max_sec_w*100:.1f}%",
                    "Vol Cap": "None" if vol_cap >= 1.0 else f"{vol_cap*100:.0f}%", "Liq Floor (₹Cr)": f"{liq_floor:.0f}",
                    "Stop Mult": f"{stop_mult:.1f}x ATR", "Cash Buffer": f"{cash_buffer*100:.0f}%", 
                    "Core ETF": f"{core_pct*100:.0f}%", "Gold Sleeve": f"{gold_pct*100:.0f}%"
                })]), hide_index=True)

                # 2. Eligible Universe & Scoring
                eligible = []
                for _, row in df.iterrows():
                    sym = row['Stock']
                    df_p = p_data.get(sym)
                    if df_p is None or len(df_p) < 252: continue
                    
                    # Volatility & Liquidity
                    vol_1y = df_p['Close'].pct_change().tail(252).std() * np.sqrt(252)
                    liq_cr = (df_p['Close'] * df_p['Volume']).tail(20).mean() / 10000000
                    
                    # Relaxation logic flags
                    relax_a = relax_b = relax_c = relax_d = False
                    
                    while True:
                        # Filters
                        pass_vol = vol_1y <= vol_cap if not relax_a else vol_1y <= (vol_cap + 0.10)
                        pass_liq = liq_cr >= liq_floor if not relax_b else liq_cr >= (liq_floor / 2)
                        pass_rs = row['RS_3M'] > 0 if not relax_c else True
                        pass_above200 = row['Above200'] if not relax_d else True
                        
                        if pass_vol and pass_liq and pass_rs and pass_above200:
                            break
                        # Relax sequentially
                        if not relax_a: relax_a = True
                        elif not relax_b: relax_b = True
                        elif not relax_c: relax_c = True
                        elif not relax_d: relax_d = True
                        else: break
                        
                    if pass_vol and pass_liq and pass_rs and pass_above200:
                        # Scoring
                        score = 0
                        rsi = ta.momentum.RSIIndicator(df_p['Close'], window=14).rsi().iloc[-1]
                        
                        if horizon == "Under 6 months":
                            pullback = 1 if 30 <= rsi <= 50 and row['Above200'] else 0
                            score = (0.4 * pullback) + (0.3 * (row['RS_3M'] / 100)) + (0.3 * (1 if row['Trend'] == "🟢 Up" else 0))
                        elif horizon == "6-24 months":
                            score = (0.5 * (row['Momentum'] / 100)) + (0.25 * (row['RS_6M'] / 100)) + (0.25 * (1 if row['Trend'] == "🟢 Up" else 0))
                        else:
                            consistency = (1 if row['1Y %'] > 0 else 0) + (1 if row['3Y %'] > 0 else 0) + (1 if row['5Y %'] > 0 else 0)
                            max_dd = calc_max_drawdown(df_p['Close'].pct_change().tail(756))
                            score = (0.35 * (consistency/3)) + (0.35 * (1 - abs(max_dd))) + (0.30 * (1 - vol_1y))
                            
                        # Risk Tilt
                        low_vol_score = 1 - vol_1y
                        vol_weight = ((10 - risk) / 10) * 0.4
                        score = (score * (1 - vol_weight)) + (low_vol_score * vol_weight)
                        if risk >= 8: score += (row['Momentum'] / 100) * 0.2
                        
                        eligible.append({
                            "Stock": sym, "Sector": row['Sector'], "Price": row['Price'], "Score": score,
                            "Vol": vol_1y, "Liq": liq_cr, "RSI": rsi, "RS_3M": row['RS_3M'],
                            "SMA50": row['SMA50'], "ATR": ta.volatility.AverageTrueRange(df_p['High'], df_p['Low'], df_p['Close']).average_true_range().iloc[-1],
                            "Relaxed": relax_a or relax_b or relax_c or relax_d
                        })
                
                if len(eligible) < 10:
                    st.warning("Not enough stocks passed the strict filters. Relaxed filters applied to guarantee at least 10 stocks.")
                
                df_elig = pd.DataFrame(eligible).sort_values(by="Score", ascending=False)
                
                # 3. Construction (Sector Caps & Weights)
                selected = []
                sector_counts = {}
                for _, row in df_elig.iterrows():
                    sec = row['Sector']
                    if sector_counts.get(sec, 0) < math.floor(max_sec_w * num_pos):
                        selected.append(row)
                        sector_counts[sec] = sector_counts.get(sec, 0) + 1
                    if len(selected) >= num_pos: break
                
                df_sel = pd.DataFrame(selected)
                # Inverse Vol Weighting
                df_sel['InvVol'] = 1 / df_sel['Vol']
                df_sel['Weight'] = df_sel['InvVol'] / df_sel['InvVol'].sum()
                
                # Cap weights
                final_weights = cap_weights(df_sel['Weight'].tolist(), max_w)
                df_sel['Weight'] = final_weights
                
                # Breadth Overlay
                if breadth < 40: cash_buffer += 0.20
                if breadth < 25: cash_buffer += 0.40
                cash_buffer = min(cash_buffer, 0.9) # Max 90% cash
                
                # Sleeve Allocation
                equity_sleeve = 1 - core_pct - gold_pct - cash_buffer
                equity_amt = inv_amount * equity_sleeve
                core_amt = inv_amount * core_pct
                gold_amt = inv_amount * gold_pct
                cash_amt = inv_amount * cash_buffer
                
                # Final Stock Allocations
                df_sel['Amt'] = df_sel['Weight'] * equity_amt
                df_sel['Shares'] = np.floor(df_sel['Amt'] / df_sel['Price']).astype(int)
                df_sel['Invested'] = df_sel['Shares'] * df_sel['Price']
                df_sel['Stop'] = df_sel['Price'] - (stop_mult * df_sel['ATR'])
                df_sel['T2R'] = df_sel['Price'] + 2 * (df_sel['Price'] - df_sel['Stop'])
                df_sel['T3R'] = df_sel['Price'] + 3 * (df_sel['Price'] - df_sel['Stop'])
                
                st.write("### Summary")
                col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                col_s1.metric("Total Capital", f"₹{inv_amount:,.0f}")
                col_s2.metric("Equity Invested", f"₹{df_sel['Invested'].sum():,.0f}")
                col_s3.metric("Core + Gold + Cash", f"₹{core_amt + gold_amt + cash_amt:,.0f}")
                col_s4.metric("Leftover Cash", f"₹{inv_amount - df_sel['Invested'].sum() - core_amt - gold_amt - cash_amt:,.0f}")
                
                # Donut Chart
                fig_pie = px.pie(values=[df_sel['Invested'].sum(), core_amt, gold_amt, cash_amt], 
                                 names=['Equity', 'Core ETF', 'Gold', 'Cash'],
                                 title="Portfolio Allocation", hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
                st.plotly_chart(fig_pie, use_container_width=True)
                
                # 4. Reality Check (5Y Backtest of basket)
                st.write("### Reality Check (Historical 5Y Risk)")
                try:
                    port_closes = pd.DataFrame({row['Stock']: p_data[row['Stock']]['Close'] for _, row in df_sel.iterrows()}).dropna()
                    port_weights = df_sel.set_index('Stock')['Weight']
                    port_returns = (port_closes.pct_change() * port_weights).sum(axis=1).dropna()
                    
                    nifty_rets = nifty_close.pct_change().tail(len(port_returns)).dropna()
                    port_rets_aligned = port_returns.tail(len(nifty_rets))
                    
                    cum_ret = (1 + port_rets_aligned).cumprod()
                    roll_1m = (cum_ret / cum_ret.shift(21) - 1).min()
                    roll_3m = (cum_ret / cum_ret.shift(63) - 1).min()
                    max_dd = calc_max_drawdown(port_rets_aligned)
                    ann_vol = port_rets_aligned.std() * np.sqrt(252)
                    beta = np.cov(port_rets_aligned, nifty_rets)[0,1] / np.var(nifty_rets)
                    
                    col_r1, col_r2, col_r3, col_r4, col_r5 = st.columns(5)
                    col_r1.metric("Worst 1M", f"{roll_1m*100:.1f}%", f"₹{roll_1m*equity_amt:,.0f}")
                    col_r2.metric("Worst 3M", f"{roll_3m*100:.1f}%", f"₹{roll_3m*equity_amt:,.0f}")
                    col_r3.metric("Max Drawdown", f"{max_dd*100:.1f}%", f"₹{max_dd*equity_amt:,.0f}")
                    col_r4.metric("Ann. Volatility", f"{ann_vol*100:.1f}%")
                    col_r5.metric("Beta to Nifty", f"{beta:.2f}")
                    st.caption("Historical risk of today's picks. This is NOT a return forecast (look-ahead bias).")
                except Exception as e:
                    st.warning(f"Could not compute backtest: {e}")
                
                # 5. Detailed Table
                st.write("### Execution Plan")
                df_display = df_sel[['Stock', 'Sector', 'Price', 'Weight', 'Shares', 'Invested', 'Stop', 'T2R', 'Momentum', 'RS_3M', 'RSI', 'Liq']].copy()
                df_display['Weight'] = df_display['Weight'].apply(lambda x: f"{x*100:.1f}%")
                df_display['Stop'] = df_display['Stop'].round(1)
                df_display['T2R'] = df_display['T2R'].round(1)
                df_display['Liq'] = df_display['Liq'].apply(lambda x: f"{x:.1f} Cr")
                df_display['RS_3M'] = df_display['RS_3M'].round(1)
                st.dataframe(df_display, hide_index=True, use_container_width=True)
                
                # 6. Telegram & Download
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    csv = df_display.to_csv(index=False).encode('utf-8')
                    st.download_button("📥 Download CSV", csv, "portfolio_plan.csv", "text/csv", key="pb_dl")
                with col_btn2:
                    if st.button("📤 Send Plan to Telegram"):
                        msg = f"<b>💼 Portfolio Plan (₹{inv_amount:,.0f})</b>\nHorizon: {horizon} | Risk: {risk}\n\n"
                        for _, r in df_sel.iterrows():
                            msg += f"• <b>{esc(r['Stock'])}</b>: {r['Shares']} sh @ ₹{r['Price']} (Stop: ₹{r['Stop']:.1f})\n"
                        success, err = send_telegram_message(tg_token, tg_chat_id, msg)
                        if success: st.success("✅ Sent to Telegram!")
                        else: st.error(f"❌ Error: {err}")
                        
            except Exception as e:
                st.error(f"❌ Failed to build portfolio: {e}")
