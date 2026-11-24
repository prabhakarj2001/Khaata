
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from scanner_core import run_scan, telegram_quality_gate

IST = ZoneInfo("Asia/Kolkata")
TOKEN = os.getenv("TG_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")


def send_telegram(text: str) -> None:
    if not TOKEN or not CHAT_ID:
        print("Telegram skipped: TG_TOKEN / TG_CHAT_ID missing.")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    chunks = []
    while len(text) > 3900:
        cut = text.rfind("\n", 0, 3900)
        if cut < 1:
            cut = 3900
        chunks.append(text[:cut])
        text = text[cut:].lstrip()

    chunks.append(text)

    for chunk in chunks:
        response = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": chunk},
            timeout=25
        )
        response.raise_for_status()


def every_third_calendar_day() -> bool:
    return (datetime.now(IST).day - 1) % 3 == 0


def fmt(value, decimals=2, suffix=""):
    try:
        if pd.isna(value):
            return "n/a"
        return f"{float(value):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "n/a"


def stock_details(r, category):
    ticker = r.get("ticker", "Unknown")
    price = fmt(r.get("price"))
    rsi = fmt(r.get("rsi"), 1)
    cmf = fmt(r.get("cmf"), 2)
    ret3 = fmt(r.get("return_3d"), 2, "%")
    ret5 = fmt(r.get("return_5d"), 2, "%")

    line = (
        f"{ticker} | ₹{price}\n"
        f"   RSI: {rsi} | CMF: {cmf} | 3D: {ret3} | 5D: {ret5}"
    )

    if category in ["STRONG BUY", "WEAK BUY",
                    "STRONG SELL", "WEAK SELL"]:
        line += (
            f"\n   SL: ₹{fmt(r.get('stop_loss'))}"
            f" | 2R: ₹{fmt(r.get('target_2r'))}"
            f" | 3R: ₹{fmt(r.get('target_3r'))}"
        )

    return line


def main():
    now = datetime.now(IST)
    print(f"Scanner started: {now.isoformat()}")

    signals, backtest, summary, failures = run_scan()

    signals.to_csv("latest_signals.csv", index=False)
    backtest.to_csv("backtest_observations.csv", index=False)
    summary.to_csv("backtest_summary.csv", index=False)

    print("\nBACKTEST SUMMARY")
    print(summary.to_string(index=False) if not summary.empty else "Unavailable")

    if not every_third_calendar_day():
        print("Not a Telegram alert day. CSV reports generated; Telegram skipped.")
        return

    gate_passed, gate_reason = telegram_quality_gate(summary)

    lines = [
        "================================",
        "       KHAATA MARKET SCANNER",
        "================================",
        f"Date: {now.strftime('%d-%m-%Y %H:%M IST')}",
        f"Quality Gate: {gate_reason}",
        "",
        "========== BACKTEST =========="
    ]

    if not summary.empty:
        for _, r in summary.iterrows():
            lines.append(
                f"{r['horizon']} | "
                f"Hit: {fmt(r['hit_rate_pct'], 2, '%')} | "
                f"Avg: {fmt(r['avg_return_pct'], 2, '%')} | "
                f"Payoff: {fmt(r['payoff_ratio'])} | "
                f"Edge: {fmt(r['benchmark_edge_pp'], 2, 'pp')}"
            )
    else:
        lines.append("Backtest data unavailable.")

    lines.extend([
        "",
        "========== TRADING SIGNALS =========="
    ])

    categories = [
        ("STRONG BUY", "🟢 STRONG BUY"),
        ("WEAK BUY", "🟩 WEAK BUY"),
        ("STRONG SELL", "🔴 STRONG SELL"),
        ("WEAK SELL", "🟥 WEAK SELL"),
        ("HOLD", "⚪ HOLD")
    ]

    if gate_passed:
        if signals.empty:
            lines.append("No stocks available.")
        else:
            for category, heading in categories:
                group = signals[signals["signal"] == category]

                lines.extend([
                    "",
                    f"--- {heading} ({len(group)}) ---"
                ])

                if group.empty:
                    lines.append("No stocks in this category.")
                    continue

                for _, r in group.iterrows():
                    lines.append(stock_details(r, category))
                    lines.append("")

    else:
        lines.extend([
            "",
            "BUY/SELL SIGNALS WITHHELD",
            f"Reason: {gate_reason}",
            "Review backtest results before acting."
        ])

        # Still display HOLD stocks when the quality gate fails.
        if not signals.empty:
            group = signals[signals["signal"] == "HOLD"]
            lines.extend(["", f"--- ⚪ HOLD ({len(group)}) ---"])

            for _, r in group.iterrows():
                lines.append(stock_details(r, "HOLD"))
                lines.append("")

    # TOP 10 PERFORMERS OVER 3 TRADING SESSIONS
    lines.extend([
        "",
        "================================",
        " TOP 10 PERFORMERS - LAST 3 DAYS",
        "================================"
    ])

    if not signals.empty and "return_3d" in signals.columns:
        performers = signals.copy()
        performers["return_3d"] = pd.to_numeric(
            performers["return_3d"], errors="coerce"
        )
        performers = performers.dropna(subset=["return_3d"])
        performers = performers.sort_values(
            "return_3d", ascending=False
        ).head(10)

        if performers.empty:
            lines.append("3-day performance data unavailable.")
        else:
            for rank, (_, r) in enumerate(performers.iterrows(), start=1):
                lines.append(
                    f"{rank}. {r['ticker']} | "
                    f"₹{fmt(r.get('price'))} | "
                    f"3D Return: {fmt(r.get('return_3d'), 2, '%')}"
                )
    else:
        lines.append(
            "3-day return field missing. Check scanner_core.py."
        )

    if failures:
        lines.extend([
            "",
            f"========== DATA FAILURES ({len(failures)}) =========="
        ])
        lines.extend(failures[:30])

    lines.extend([
        "",
        "================================",
        "       END OF SCAN REPORT",
        "================================"
    ])

    send_telegram("\n".join(lines))
    print("Scheduled scan completed.")


if __name__ == "__main__":
    main()
