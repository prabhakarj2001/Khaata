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
            url, data={"chat_id": CHAT_ID, "text": chunk}, timeout=25
        )
        response.raise_for_status()


def every_third_calendar_day() -> bool:
    # Alert on days 1, 4, 7, 10 ...; scheduled workflow itself runs weekdays.
    return (datetime.now(IST).day - 1) % 3 == 0


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
        "KHAATA MARKET SCANNER",
        f"Date: {now.strftime('%d-%m-%Y %H:%M IST')}",
        f"Telegram quality gate: {gate_reason}",
        "",
        "BACKTEST SUMMARY (RSI<40 historical entries)"
    ]

    if not summary.empty:
        for _, r in summary.iterrows():
            def fmt(value, suffix=""):
                return "n/a" if pd.isna(value) else f"{value:.2f}{suffix}"
            lines.append(
                f"{r['horizon']}: n={int(r['observations'])}, "
                f"hit={fmt(r['hit_rate_pct'], '%')}, "
                f"avg={fmt(r['avg_return_pct'], '%')}, "
                f"payoff={fmt(r['payoff_ratio'])}, "
                f"benchmark edge={fmt(r['benchmark_edge_pp'], 'pp')}"
            )

    if gate_passed:
        lines.extend(["", "CURRENT SIGNALS"])
        if signals.empty:
            lines.append("No qualifying signals today.")
        else:
            for category in ["STRONG BUY", "WEAK BUY", "STRONG SELL", "WEAK SELL", "HOLD"]:
                group = signals[signals["signal"] == category]
                if group.empty:
                    continue
                lines.extend(["", f"{category} ({len(group)})"])
                for _, r in group.iterrows():
                    lines.append(
                        f"{r['ticker']} | ₹{r['price']:.2f} | RSI {r['rsi']:.1f} | "
                        f"CMF {r['cmf']:.2f} | 5D {r['return_5d']:.2f}% | "
                        f"SL ₹{r['stop_loss']:.2f} | "
                        f"2R ₹{r['target_2r']:.2f} | 3R ₹{r['target_3r']:.2f}"
                    )
    else:
        lines.extend([
            "",
            "LIVE BUY/SELL SIGNALS WITHHELD",
            "The backtest quality gate was not met. Review the CSV reports first."
        ])

    if failures:
        lines.extend(["", f"DATA FAILURES ({len(failures)})"])
        lines.extend(failures[:30])

    send_telegram("\n".join(lines))
    print("Scheduled scan completed.")


if __name__ == "__main__":
    main()
