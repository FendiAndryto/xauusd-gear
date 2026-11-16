"""
Fetch and cache M1/M5/M15 bars and Parquet ticks for Months 01, 02, 03 of 2026 from MT5.
"""

import os
import sys
import time
from datetime import datetime, timezone
import pandas as pd
import MetaTrader5 as mt5

CACHE_DIR = "data/cache_bars"
PARQUET_BASE = "data/parquet/xauusd/year=2026"
os.makedirs(CACHE_DIR, exist_ok=True)


def ingest_and_cache_month(year: int, month: int):
    month_str = f"{month:02d}"
    cache_m1 = os.path.join(CACHE_DIR, f"m1_{year}_{month_str}.parquet")
    cache_m5 = os.path.join(CACHE_DIR, f"m5_{year}_{month_str}.parquet")
    cache_m15 = os.path.join(CACHE_DIR, f"m15_{year}_{month_str}.parquet")
    parquet_dir = os.path.join(PARQUET_BASE, f"month={month_str}")
    os.makedirs(parquet_dir, exist_ok=True)
    parquet_file = os.path.join(parquet_dir, "ticks.parquet")

    if os.path.exists(cache_m1) and os.path.exists(cache_m5) and os.path.exists(cache_m15) and os.path.exists(parquet_file):
        print(f"Month {month_str} already cached and saved to parquet.")
        return

    print(f"\n--- Processing Month {month_str}/{year} ---")
    start_dt = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end_dt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end_dt = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    t0 = time.time()
    print(f"Copying ticks from MT5 for {year}-{month_str} ({start_dt} to {end_dt})...")
    ticks = mt5.copy_ticks_range('XAUUSDm', start_dt, end_dt, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        print(f"ERROR: No ticks returned for {year}-{month_str}")
        return

    print(f"Retrieved {len(ticks):,} ticks in {time.time()-t0:.2f}s! Converting to DataFrame...")
    t1 = time.time()
    df = pd.DataFrame(ticks)
    df['timestamp'] = pd.to_datetime(df['time_msc'], unit='ms', utc=True)
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    df['mid'] = (df['bid'] + df['ask']) / 2.0
    print(f"DataFrame built in {time.time()-t1:.2f}s. Resampling M1, M5, M15...")

    t2 = time.time()
    m1 = df['mid'].resample('1min').ohlc().dropna()
    m5 = df['mid'].resample('5min').ohlc().dropna()
    m15 = df['mid'].resample('15min').ohlc().dropna()
    print(f"Resampled in {time.time()-t2:.2f}s: M1={len(m1):,} bars, M5={len(m5):,} bars, M15={len(m15):,} bars.")

    # Cache bars
    m1.to_parquet(cache_m1)
    m5.to_parquet(cache_m5)
    m15.to_parquet(cache_m15)
    print(f"Saved bar caches to {CACHE_DIR}")

    # Save ticks parquet
    if not os.path.exists(parquet_file):
        t3 = time.time()
        print(f"Saving ticks to {parquet_file}...")
        save_df = df[['bid', 'ask', 'flags']].reset_index()
        save_df.to_parquet(parquet_file, compression='zstd')
        print(f"Saved ticks parquet in {time.time()-t3:.2f}s ({os.path.getsize(parquet_file)/1e6:.1f} MB).")


def main():
    if not mt5.initialize(r'C:\MetaTrader 5 - RESEARCH - EA\terminal64.exe'):
        print("Failed to initialize MT5:", mt5.last_error())
        sys.exit(1)

    mt5.symbol_select('XAUUSDm', True)

    for m in [1, 2, 3]:
        ingest_and_cache_month(2026, m)

    mt5.shutdown()
    print("\nAll target months (01, 02, 03) ingested and cached successfully!")


if __name__ == "__main__":
    main()
