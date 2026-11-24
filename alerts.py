
import os
from datetime import datetime
import pandas as pd
import yfinance as yf
import requests
import ta

# Telegram credentials are read securely from GitHub Actions Secrets
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

STOCKS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "INFY.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS",
    "LT.NS", "KOTAKBANK.NS", "AXISBANK.NS", "HINDUNILVR.NS",
    "BAJFINANCE.NS", "MARUTI.NS", "TATASTEEL.NS", "SUNPHARMA.NS",
    "TITAN.NS", "ULTRACEMCO.NS", "WIPRO.NS", "NESTLEIND.NS",
    "POWERGRID.NS", "NTPC.NS", "TECHM.NS", "HCLTECH.NS",
    "ADANIENT.NS", "ADANIPORTS.NS"
]

METALS = {
    "Gold": "GC=F",
    "Silver": "SI=F",
    "Copper": "HG=F",
    "Platinum": "PL=F",
    "Palladium": "PA=F"
}

def send_telegram_message(message):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("ERROR: TG_TOKEN or TG_CHAT_ID is missing.")
        return

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"

    # Telegram message limit is 4096 characters.
    # Use a smaller limit to avoid formatting issues.
    chunks = []
    while len(message) > 3900:
        split_at = message.rfind("\n", 0, 3900)
        if split_at == -1:
            split_at = 3900
        chunks.append(message[:split_at])
        message = message[split_at:].lstrip()

    chunks.append(message)

    for chunk in chunks:
        try:
            response = requests.post(
                url,
                data={"chat_id": TG_CHAT_ID, "text": chunk},
                timeout=20
            )
            response.raise_for_status()
            print("Telegram message sent.")
        except requests.RequestException as error:
            print(f"Telegram error: {error}")


def get_stock_data(ticker):
    try:
        data = yf.download(
            ticker,
            period="1y",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False
        )

        if data.empty:
            return None

        # Handle both normal and MultiIndex yfinance columns
        if isinstance(data.columns, pd.MultiIndex):
            close = data["Close"].iloc[:, 0]
            volume = data["Volume"].iloc[:, 0]
        else:
            close = data["Close"]
            volume = data["Volume"]

        df = pd.DataFrame({
            "Close": close,
            "Volume": volume
        }).dropna()

        if len(df) < 50:
            return None

        return df

    except Exception as error:
        print(f"Data error for {ticker}: {error}")
        return None


def analyse_stock(ticker):
    df = get_stock_data(ticker)

    if df is None:
        return None

    close = df["Close"]
    volume = df["Volume"]

    rsi = ta.momentum.RSIIndicator(close, window=14).rsi()
    macd_obj = ta.trend.MACD(
        close,
        window_slow=26,
        window_fast=12,
        window_sign=9
    )

    macd = macd_obj.macd()
    signal = macd_obj.macd_signal()

    latest_rsi = rsi.iloc[-1]
    latest_macd = macd.iloc[-1]
    latest_signal = signal.iloc[-1]
    latest_price = close.iloc[-1]

    if pd.isna(latest_rsi) or pd.isna(latest_signal):
        return None

    # Volume spike: current volume is above 1.5x its 20-day average
    avg_volume = volume.rolling(20).mean().iloc[-1]
    volume_spike = (
        pd.notna(avg_volume)
        and avg_volume > 0
        and volume.iloc[-1] > 1.5 * avg_volume
    )

    momentum = (
        (latest_price / close.iloc[-21] - 1) * 100
        if len(close) >= 21 else 0
    )

    # Signal classification
    if latest_rsi < 40 and latest_macd > latest_signal:
        category = "STRONG BUY"
    elif latest_rsi < 40:
        category = "WEAK BUY"
    elif latest_rsi > 60 and latest_macd < latest_signal:
        category = "STRONG SELL"
    elif latest_rsi > 60:
        category = "WEAK SELL"
    else:
        return None

    impact = abs(latest_rsi - 50) + abs(momentum) * 0.5
    if volume_spike:
        impact += 10

    return {
        "ticker": ticker.replace(".NS", ""),
        "category": category,
        "price": latest_price,
        "rsi": latest_rsi,
        "momentum": momentum,
        "volume_spike": volume_spike,
        "impact": impact
    }


def get_all_signals():
    categories = {
        "STRONG BUY": [],
        "WEAK BUY": [],
        "STRONG SELL": [],
        "WEAK SELL": []
    }

    print("Starting stock scan...")

    for ticker in STOCKS:
        result = analyse_stock(ticker)

        if result:
            categories[result["category"]].append(result)
            print(f"{ticker}: {result['category']}")

    # Highest-impact signals first within each category
    for category in categories:
        categories[category].sort(
            key=lambda x: x["impact"],
            reverse=True
        )

    return categories


def get_top_10_momentum():
    results = []

    for ticker in STOCKS:
        df = get_stock_data(ticker)

        if df is None or len(df) < 252:
            continue

        close = df["Close"]

        daily_return = close.pct_change().iloc[-1] * 100
        monthly_return = (close.iloc[-1] / close.iloc[-21] - 1) * 100
        yearly_return = (close.iloc[-1] / close.iloc[-252] - 1) * 100

        score = (
            daily_return * 0.2
            + monthly_return * 0.3
            + yearly_return * 0.5
        )

        results.append({
            "ticker": ticker.replace(".NS", ""),
            "score": score,
            "monthly": monthly_return,
            "yearly": yearly_return
        })

    return sorted(
        results,
        key=lambda x: x["score"],
        reverse=True
    )[:10]


def get_metals_report():
    lines = ["METALS RSI REPORT"]

    for name, ticker in METALS.items():
        try:
            data = yf.download(
                ticker,
                period="6mo",
                interval="1d",
                auto_adjust=True,
                progress=False
            )

            if data.empty:
                lines.append(f"{name}: Data unavailable")
                continue

            if isinstance(data.columns, pd.MultiIndex):
                close = data["Close"].iloc[:, 0]
            else:
                close = data["Close"]

            rsi = ta.momentum.RSIIndicator(close, window=14).rsi()
            latest_rsi = rsi.iloc[-1]

            if pd.isna(latest_rsi):
                lines.append(f"{name}: Insufficient data")
                continue

            if latest_rsi >= 70:
                status = "OVERBOUGHT"
            elif latest_rsi <= 30:
                status = "OVERSOLD"
            else:
                status = "NEUTRAL"

            lines.append(f"{name}: RSI {latest_rsi:.1f} — {status}")

        except Exception as error:
            print(f"Metal data error for {name}: {error}")
            lines.append(f"{name}: Data unavailable")

    return "\n".join(lines)


def build_report():
    now = datetime.now()
    categories = get_all_signals()

    lines = [
        "MARKET SCANNER ALERT",
        f"Date: {now.strftime('%d-%m-%Y')}",
        "",
        "BUY / SELL SIGNALS",
        "=================="
    ]

    total = sum(len(items) for items in categories.values())
    lines.append(f"Total qualifying signals: {total}")

    # Strict priority: all Strong Buys first
    for category in [
        "STRONG BUY",
        "WEAK BUY",
        "STRONG SELL",
        "WEAK SELL"
    ]:
        items = categories[category]

        lines.extend([
            "",
            f"{category} ({len(items)})",
            "--------------------"
        ])

        if not items:
            lines.append("No signals.")
            continue

        for item in items:
            volume_text = " | Volume spike" if item["volume_spike"] else ""

            lines.append(
                f"{item['ticker']} | "
                f"Price: {item['price']:.2f} | "
                f"RSI: {item['rsi']:.1f} | "
                f"21D Return: {item['momentum']:.2f}%"
                f"{volume_text}"
            )

    # Top 10 momentum report
    lines.extend(["", "TOP 10 MOMENTUM STOCKS", "======================"])

    momentum = get_top_10_momentum()

    if momentum:
        for index, stock in enumerate(momentum, 1):
            lines.append(
                f"{index}. {stock['ticker']} | "
                f"Score: {stock['score']:.2f} | "
                f"Monthly: {stock['monthly']:.2f}% | "
                f"Yearly: {stock['yearly']:.2f}%"
            )
    else:
        lines.append("Momentum data unavailable.")

    lines.extend(["", get_metals_report()])

    return "\n".join(lines)


def check_and_send():
    now = datetime.now()

    # Run on every third calendar day: 1st, 4th, 7th, 10th, etc.
    if (now.day - 1) % 3 != 0:
        print("Not a scheduled alert day. Skipping.")
        return

    print("Scheduled scan started.")

    report = build_report()
    send_telegram_message(report)

    print("Scan completed.")


if __name__ == "__main__":
    check_and_send()
