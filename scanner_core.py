from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
import ta

IST = ZoneInfo("Asia/Kolkata")

# NSE universe: original 26 names plus Mahindra & Mahindra.
TICKERS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "INFY.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS",
    "KOTAKBANK.NS", "AXISBANK.NS", "HINDUNILVR.NS", "BAJFINANCE.NS",
    "MARUTI.NS", "TATASTEEL.NS", "SUNPHARMA.NS", "TITAN.NS",
    "ULTRACEMCO.NS", "WIPRO.NS", "NESTLEIND.NS", "POWERGRID.NS",
    "NTPC.NS", "TECHM.NS", "HCLTECH.NS", "ADANIENT.NS",
    "ADANIPORTS.NS", "M&M.NS"
]
BENCHMARK = "^NSEI"


def _extract_series(raw: pd.DataFrame, field: str, ticker: str) -> pd.Series:
    """Handle both flat and yfinance MultiIndex column layouts."""
    if isinstance(raw.columns, pd.MultiIndex):
        if field in raw.columns.get_level_values(0):
            obj = raw[field]
            return obj.iloc[:, 0] if isinstance(obj, pd.DataFrame) else obj
        if field in raw.columns.get_level_values(-1):
            obj = raw.xs(field, axis=1, level=-1)
            return obj.iloc[:, 0] if isinstance(obj, pd.DataFrame) else obj
    obj = raw[field]
    return obj.iloc[:, 0] if isinstance(obj, pd.DataFrame) else obj


def download_daily(ticker: str, period: str = "5y") -> pd.DataFrame:
    """Download adjusted daily OHLCV and discard a still-forming daily candle."""
    raw = yf.download(
        ticker, period=period, interval="1d", auto_adjust=True,
        progress=False, threads=False
    )
    if raw is None or raw.empty:
        raise ValueError("No data returned")

    df = pd.DataFrame(index=raw.index)
    for field in ("Open", "High", "Low", "Close", "Volume"):
        df[field] = _extract_series(raw, field, ticker)

    df = df[~df.index.duplicated(keep="last")].sort_index().dropna(
        subset=["High", "Low", "Close"]
    )

    # Daily bars are normally complete after NSE close. If run before 15:35 IST,
    # remove today's bar so an in-progress session cannot create a false signal.
    now = datetime.now(IST)
    last_date = pd.Timestamp(df.index[-1]).date()
    if last_date == now.date() and now.time() < time(15, 35):
        df = df.iloc[:-1]

    if len(df) < 260:
        raise ValueError(f"Only {len(df)} completed sessions; need at least 260")
    return df


def get_ret(close: pd.Series, sessions: int) -> float:
    """Exact N-trading-session return. NaN if the full lookback is unavailable."""
    if len(close) <= sessions:
        return float("nan")
    start = close.iloc[-(sessions + 1)]
    end = close.iloc[-1]
    if pd.isna(start) or pd.isna(end) or start == 0:
        return float("nan")
    return float((end / start - 1.0) * 100.0)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close, high, low, volume = out["Close"], out["High"], out["Low"], out["Volume"]

    out["RSI14"] = ta.momentum.RSIIndicator(close, window=14).rsi()
    macd_obj = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    out["MACD"] = macd_obj.macd()
    out["MACD_SIGNAL"] = macd_obj.macd_signal()
    out["SMA50"] = close.rolling(50, min_periods=50).mean()
    out["SMA200"] = close.rolling(200, min_periods=200).mean()
    out["ATR14"] = ta.volatility.AverageTrueRange(
        high, low, close, window=14
    ).average_true_range()
    out["CMF20"] = ta.volume.ChaikinMoneyFlowIndicator(
        high, low, close, volume, window=20
    ).chaikin_money_flow()

    out["VOL_AVG20_PRIOR"] = volume.shift(1).rolling(20, min_periods=20).mean()
    out["VOLUME_SPIKE"] = (
        out["VOL_AVG20_PRIOR"].notna()
        & (volume > 1.5 * out["VOL_AVG20_PRIOR"])
    )

    daily = close.pct_change()
    # 6M/12M momentum excludes the latest 21 trading sessions.
    out["MOM6M_EX21"] = close.shift(21) / close.shift(126) - 1
    out["MOM12M_EX21"] = close.shift(21) / close.shift(252) - 1

    vol6 = daily.rolling(126, min_periods=100).std() * np.sqrt(252)
    vol12 = daily.rolling(252, min_periods=200).std() * np.sqrt(252)
    out["VOL_ADJ_MOM6M"] = out["MOM6M_EX21"] / vol6.replace(0, np.nan)
    out["VOL_ADJ_MOM12M"] = out["MOM12M_EX21"] / vol12.replace(0, np.nan)
    out["VOL_ADJ_MOM_SCORE"] = (
        out["VOL_ADJ_MOM6M"] * 0.5 + out["VOL_ADJ_MOM12M"] * 0.5
    )
    out["RETURN_5D"] = close.pct_change(5) * 100
    return out


def classify_latest(ticker: str, df: pd.DataFrame) -> Optional[dict]:
    row = add_indicators(df).iloc[-1]
    required = ["RSI14", "MACD", "MACD_SIGNAL", "SMA50", "ATR14", "CMF20"]
    if any(pd.isna(row[k]) for k in required):
        return None

    price = float(row["Close"])
    rsi = float(row["RSI14"])
    cmf = float(row["CMF20"])
    macd_down = float(row["MACD"]) < float(row["MACD_SIGNAL"])
    below_50 = price < float(row["SMA50"])

    # CMF grades the RSI oversold setup; exit logic follows 50DMA/MACD.
    if rsi < 40 and cmf > 0:
        signal = "STRONG BUY"
    elif rsi < 40:
        signal = "WEAK BUY"
    elif below_50 and macd_down:
        signal = "STRONG SELL"
    elif below_50 or macd_down:
        signal = "WEAK SELL"
    else:
        signal = "HOLD"

    atr = float(row["ATR14"])
    stop = price - 2 * atr
    risk = price - stop
    return {
        "ticker": ticker,
        "signal": signal,
        "price": price,
        "rsi": rsi,
        "cmf": cmf,
        "return_5d": get_ret(df["Close"], 5),
        "sma50": float(row["SMA50"]),
        "sma200": float(row["SMA200"]) if pd.notna(row["SMA200"]) else np.nan,
        "atr14": atr,
        "stop_loss": stop,
        "target_2r": price + 2 * risk,
        "target_3r": price + 3 * risk,
        "volume_spike": bool(row["VOLUME_SPIKE"]),
        "mom6m_ex21": float(row["MOM6M_EX21"]) if pd.notna(row["MOM6M_EX21"]) else np.nan,
        "mom12m_ex21": float(row["MOM12M_EX21"]) if pd.notna(row["MOM12M_EX21"]) else np.nan,
        "vol_adj_mom": float(row["VOL_ADJ_MOM_SCORE"]) if pd.notna(row["VOL_ADJ_MOM_SCORE"]) else np.nan,
        "macd_down": macd_down,
        "below_50dma": below_50,
    }


def backtest_universe(history: dict[str, pd.DataFrame], benchmark: pd.DataFrame) -> pd.DataFrame:
    """Historical RSI<40 entry study with 5/20/60-session forward returns."""
    bench_close = benchmark["Close"]
    rows = []
    for ticker, raw in history.items():
        df = add_indicators(raw)
        close = df["Close"]
        for i in range(260, len(df) - 60):
            if pd.isna(df["RSI14"].iloc[i]) or df["RSI14"].iloc[i] >= 40:
                continue
            entry = float(close.iloc[i])
            if entry <= 0:
                continue
            date = df.index[i]
            bidx = bench_close.index.get_indexer([date], method="nearest")[0]
            if bidx < 0 or bidx + 60 >= len(bench_close):
                continue
            bentry = float(bench_close.iloc[bidx])
            record = {"ticker": ticker, "date": str(pd.Timestamp(date).date())}
            for horizon in (5, 20, 60):
                exit_price = float(close.iloc[i + horizon])
                record[f"ret_{horizon}d"] = (exit_price / entry - 1) * 100
                b_exit = float(bench_close.iloc[bidx + horizon])
                record[f"bench_{horizon}d"] = (b_exit / bentry - 1) * 100
                record[f"edge_{horizon}d"] = record[f"ret_{horizon}d"] - record[f"bench_{horizon}d"]
            rows.append(record)
    return pd.DataFrame(rows)


def summarize_backtest(bt: pd.DataFrame) -> pd.DataFrame:
    summaries = []
    for horizon in (5, 20, 60):
        col = f"ret_{horizon}d"
        edge = f"edge_{horizon}d"
        if bt.empty or col not in bt:
            summaries.append({
                "horizon": f"{horizon}D", "observations": 0,
                "hit_rate_pct": np.nan, "avg_return_pct": np.nan,
                "avg_win_pct": np.nan, "avg_loss_pct": np.nan,
                "payoff_ratio": np.nan, "benchmark_edge_pp": np.nan
            })
            continue
        vals = bt[col].dropna()
        wins, losses = vals[vals > 0], vals[vals < 0]
        avg_win = wins.mean() if len(wins) else np.nan
        avg_loss = abs(losses.mean()) if len(losses) else np.nan
        payoff = avg_win / avg_loss if pd.notna(avg_win) and pd.notna(avg_loss) and avg_loss else np.nan
        summaries.append({
            "horizon": f"{horizon}D",
            "observations": int(len(vals)),
            "hit_rate_pct": float((vals > 0).mean() * 100) if len(vals) else np.nan,
            "avg_return_pct": float(vals.mean()) if len(vals) else np.nan,
            "avg_win_pct": float(avg_win) if pd.notna(avg_win) else np.nan,
            "avg_loss_pct": float(avg_loss) if pd.notna(avg_loss) else np.nan,
            "payoff_ratio": float(payoff) if pd.notna(payoff) else np.nan,
            "benchmark_edge_pp": float(bt[edge].mean()) if len(bt[edge].dropna()) else np.nan
        })
    return pd.DataFrame(summaries)


def run_scan() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    results, history, failures = [], {}, []
    for ticker in TICKERS:
        try:
            df = download_daily(ticker, period="5y")
            history[ticker] = df
            signal = classify_latest(ticker, df)
            if signal:
                results.append(signal)
        except Exception as exc:
            failures.append(f"{ticker}: {exc}")

    signals = pd.DataFrame(results)
    if not signals.empty:
        signals = signals.sort_values(
            ["signal", "vol_adj_mom"], ascending=[True, False], na_position="last"
        )

    try:
        benchmark = download_daily(BENCHMARK, period="5y")
        bt = backtest_universe(history, benchmark)
        summary = summarize_backtest(bt)
    except Exception as exc:
        failures.append(f"Benchmark/backtest: {exc}")
        bt, summary = pd.DataFrame(), pd.DataFrame()

    return signals, bt, summary, failures


def telegram_quality_gate(summary: pd.DataFrame) -> tuple[bool, str]:
    """Require >=100 20D observations and >0.5 percentage-point edge."""
    if summary.empty:
        return False, "Backtest summary unavailable"
    row = summary.loc[summary["horizon"] == "20D"]
    if row.empty:
        return False, "20-day backtest unavailable"
    obs = int(row.iloc[0]["observations"])
    edge = row.iloc[0]["benchmark_edge_pp"]
    if obs < 100:
        return False, f"Only {obs} 20D observations; minimum required is 100"
    if pd.isna(edge) or edge <= 0.5:
        return False, f"20D benchmark edge is {edge}; must be above 0.50 percentage points"
    return True, f"Passed: {obs} observations and {edge:.2f}pp 20D edge"
