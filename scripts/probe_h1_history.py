"""Probe whether the broker actually has true H1 bars before 2021-07.

The cache holds 36 months (2018-07 .. 2021-06) whose ``h1_*`` files contain
~26 bars each — that is one bar per *day*, not per hour. Two possibilities:

1. The broker's H1 history genuinely starts later, and MetaTrader returns daily
   bars for earlier requests. Nothing can be fixed; the sparse warning is the
   honest answer.
2. The broker *does* have H1 back to 2018 and the original download silently
   got D1 data (wrong symbol, wrong constant, terminal "max bars" limit).

The tell is simple: if a month's H1 bar count equals its D1 bar count, MT5 is
serving daily bars for an hourly request. Real hourly data gives roughly 20x
more bars than daily.

    .venv\\Scripts\\python.exe scripts/probe_h1_history.py

Requires the MT5 terminal to be running and logged in. Read-only: it never
writes a parquet file.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

# Same preference order as scripts/download_history_10y.py, so this probe
# measures the symbol the cache was actually built from.
PREFERRED_SYMBOLS = ["XAUUSDm", "XAUUSD", "XAUUSD.a", "GOLD", "GOLDm"]

SAMPLES = [
    (2018, 7),
    (2019, 6),
    (2020, 1),
    (2021, 1),
    (2021, 6),
    (2021, 7),
    (2021, 8),
    (2022, 1),
    (2022, 8),
    (2026, 10),
]


def month_range(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = (
        datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=timezone.utc)
    )
    return start, end


def bar_count(mt5, symbol: str, tf: int, year: int, month: int) -> int:
    start, end = month_range(year, month)
    rates = mt5.copy_rates_range(symbol, tf, start, end)
    return 0 if rates is None else len(rates)


def resolve_symbol(mt5) -> str | None:
    """Pick the symbol the cache was built from (XAUUSDm first)."""
    for name in PREFERRED_SYMBOLS:
        if mt5.symbol_info(name) is not None and mt5.symbol_select(name, True):
            return name
    for sym in mt5.symbols_get() or []:
        if "XAU" in sym.name.upper() and mt5.symbol_select(sym.name, True):
            print(
                f"[warn] falling back to {sym.name}; none of {PREFERRED_SYMBOLS} exist"
            )
            return sym.name
    return None


def main() -> int:
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("MetaTrader5 package is not installed in this venv.")
        return 2

    if not mt5.initialize():
        print(f"MT5 initialize() failed: {mt5.last_error()}")
        print("Start the MetaTrader 5 terminal, log in, then run this again.")
        return 2

    try:
        info = mt5.terminal_info()
        account = mt5.account_info()
        print(
            f"terminal : {info.name if info else '?'}  build={info.build if info else '?'}"
        )
        print(f"server   : {account.server if account else '?'}")
        print(f"max bars : {info.maxbars if info else '?'} in chart")

        symbol = resolve_symbol(mt5)
        if not symbol:
            print("No gold symbol could be selected.")
            return 2
        print(f"symbol   : {symbol}")
        print()

        print(f"{'month':<9} {'H1':>6} {'D1':>6} {'H1/D1':>7}  verdict")
        print("-" * 46)
        first_hourly: str | None = None
        for year, month in SAMPLES:
            h1 = bar_count(mt5, symbol, mt5.TIMEFRAME_H1, year, month)
            d1 = bar_count(mt5, symbol, mt5.TIMEFRAME_D1, year, month)
            ratio = (h1 / d1) if d1 else 0.0
            hourly = d1 > 0 and ratio > 2.0
            verdict = "hourly" if hourly else ("daily fallback" if h1 else "no data")
            if hourly and first_hourly is None:
                first_hourly = f"{year}-{month:02d}"
            print(f"{year}-{month:02d}  {h1:>6} {d1:>6} {ratio:>7.1f}  {verdict}")

        print()
        if first_hourly:
            print(f"First sampled month with real hourly bars: {first_hourly}")
            print("If that is 2021-07, the cache is already the honest maximum and")
            print("the sparse warning in the UI is correct — no re-download needed.")
            print("If it is earlier than 2021-07, the 36 sparse months CAN be")
            print("replaced with real hourly data (backup, then re-download).")
        else:
            print("No sampled month returned real hourly bars; check the symbol.")

        m15_start = None
        for year, month in [(2022, 6), (2022, 7), (2022, 8), (2022, 9)]:
            if bar_count(mt5, symbol, mt5.TIMEFRAME_M15, year, month) > 100:
                m15_start = f"{year}-{month:02d}"
                break
        if m15_start:
            print(f"\nM15 intraday history starts around: {m15_start}")
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
