import pandas as pd
import yfinance as yf
import requests
import ta
from datetime import datetime

TG_TOKEN = "9015179938:AAFATXEjxrMZUwPp4csuQO6vmFdae3dBXWE"
TG_CHAT_ID = "1063631401"

def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "HTML"}
        response = requests.post(url, json=payload)
        return response.status_code == 200
    except: return False

def get_top_10_momentum():
    symbols = ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "SBIN", "BHARTIARTL", "ITC", "LT", "KOTAKBANK",
               "AXISBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI", "TATASTEEL", "SUNPHARMA", "TITAN", "ULTRACEMCO",
               "WIPRO", "NESTLEIND", "POWERGRID", "NTPC", "TECHM", "HCLTECH", "ADANIENT", "ADANIPORTS"]
    
    tickers = " ".join([s + ".NS" for s in symbols])
    data = yf.download(tickers, period="1y", interval="1d", group_by='ticker', progress=False)
    results = []
    
    for sym in symbols:
        try:
            df = data[sym + ".NS"].dropna()
            if len(df) < 50: continue
            daily_ret = df['Close'].pct_change().mean() * 100
            monthly_ret = ((df['Close'].iloc[-1] - df['Close'].iloc[-21]) / df['Close'].iloc[-21]) * 100
            yearly_ret = ((df['Close'].iloc[-1] - df['Close'].iloc[-252]) / df['Close'].iloc[-252]) * 100
            momentum_score = (daily_ret * 0.2) + (monthly_ret * 0.3) + (yearly_ret * 0.5)
            results.append({"Stock": sym, "Momentum": round(float(momentum_score), 1), "Price": round(float(df['Close'].iloc[-1]), 2)})
        except: continue
    
    return pd.DataFrame(results).sort_values(by="Momentum", ascending=False).head(10)

def get_metals_fund_flow():
    metals = {'Gold': 'GC=F', 'Silver': 'SI=F', 'Copper': 'HG=F', 'Platinum': 'PL=F', 'Palladium': 'PA=F'}
    flow_data = []
    for name, ticker in metals.items():
        try:
            df = yf.download(ticker, period="2y", interval="1d", progress=False)
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df.dropna()
            if len(df) < 50: continue
            rsi = ta.momentum.RSIIndicator(df['Close'], window=14).rsi().iloc[-1]
            status = "🔴 Overbought (Out)" if rsi > 70 else ("🟢 Oversold (In)" if rsi < 30 else "⚪ Neutral")
            flow_data.append({"Metal": name, "RSI": round(rsi, 1), "Status": status})
        except: continue
    return pd.DataFrame(flow_data)

def check_and_send():
    now = datetime.now()
    if (now.day - 1) % 3 != 0:
        print("Not a scheduled day. Skipping.")
        return

    print("Generating 3-Day report...")
    top_10 = get_top_10_momentum()
    metals_flow = get_metals_fund_flow()
    
    msg = "<b>🚨 3-Day Market Report</b>\n\n<b>🏆 Top 10 Momentum Stocks</b>\n"
    for _, row in top_10.iterrows():
        msg += f"• {row['Stock']} (Score: {row['Momentum']}) - ₹{row['Price']}\n"
        
    msg += "\n<b>🥇 Metals Fund Flow</b>\n"
    for _, row in metals_flow.iterrows():
        msg += f"• {row['Metal']}: {row['Status']} (RSI: {row['RSI']})\n"
        
    if send_telegram_message(msg): print("Sent successfully!")
    else: print("Failed to send.")

if __name__ == "__main__":
    check_and_send()
