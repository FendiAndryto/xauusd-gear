"""Historical Bar Downloader (10 Years: 2017 - 2026).

Downloads historical OHLCV bars from MetaTrader 5 for XAUUSD across M5, M15, and H1
timeframes, saving modular monthly Parquet files into `data/cache_bars/`.

Ticket: T-PAR-01
Reference Spec: SPEC-PA-REPLAY-01
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("download_10y")

TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

PREFERRED_SYMBOLS = [
    "XAUUSDm",
    "XAUUSD",
    "XAUUSD.a",
    "GOLD",
    "GOLDm",
]

# SPEC-PA-REPLAY-01 §3.3 canonical bar schema. Kept in sync with
# scripts/verify_parquet_cache.py and scripts/repair_bar_cache_schema.py.
CONTRACT_COLUMNS = (
    "time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
    "timestamp",
)


def resolve_symbol(requested: Optional[str] = None) -> str:
    """Detect and select the broker's active gold symbol."""
    if requested:
        if mt5.symbol_info(requested) is not None:
            mt5.symbol_select(requested, True)
            return requested
        logger.warning("Requested symbol '%s' not found. Auto-resolving...", requested)

    all_symbols = [s.name for s in (mt5.symbols_get() or [])]
    for pref in PREFERRED_SYMBOLS:
        if pref in all_symbols:
            mt5.symbol_select(pref, True)
            return pref

    # Fallback to any symbol containing XAU or GOLD
    for sym in all_symbols:
        upper = sym.upper()
        if "XAUUSD" in upper or "GOLD" in upper:
            mt5.symbol_select(sym, True)
            return sym

    raise RuntimeError("No gold / XAUUSD symbol found in MetaTrader 5.")


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Return UTC start and end bounds for a given calendar month."""
    start_dt = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    if month == 12:
        end_dt = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    else:
        end_dt = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return start_dt, end_dt


def fetch_month_rates(
    symbol: str,
    mt5_tf: int,
    start_dt: datetime,
    end_dt: datetime,
    max_retries: int = 3,
) -> Optional[np.ndarray]:
    """Fetch rates for a date range with automatic retry."""
    for attempt in range(1, max_retries + 1):
        rates = mt5.copy_rates_range(symbol, mt5_tf, start_dt, end_dt)
        if rates is not None and len(rates) > 0:
            return rates
        if attempt < max_retries:
            time.sleep(1.5)
    return None


def is_valid_month_data(
    rates: np.ndarray, start_dt: datetime, end_dt: datetime, min_bars: int = 10
) -> bool:
    """Ensure data is real trading bars falling within the target month."""
    if rates is None or len(rates) < min_bars:
        return False

    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    # Check timestamps: at least 90% of bars must fall inside [start_ts, end_ts)
    times = rates["time"]
    in_range = (times >= start_ts) & (times < end_ts)
    ratio = np.mean(in_range)
    return bool(ratio >= 0.90)


def save_rates_parquet(rates: np.ndarray, target_file: Path) -> int:
    """Save structured rates array to standardized Parquet file."""
    df = pd.DataFrame(rates)
    df["timestamp"] = pd.to_datetime(df["time"], unit="s")
    df["open"] = df["open"].round(2)
    df["high"] = df["high"].round(2)
    df["low"] = df["low"].round(2)
    df["close"] = df["close"].round(2)
    df = df.sort_values("time").reset_index(drop=True)

    target_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(target_file, engine="pyarrow", compression="snappy")
    return len(df)


def download_history(
    symbol: Optional[str] = None,
    start_year: int = 2017,
    end_year: int = 2026,
    timeframes: Sequence[str] = ("H1", "M15", "M5"),
    cache_dir: Path = Path("data/cache_bars"),
    force: bool = False,
) -> dict[str, Any]:
    """Download historical bars for all requested years, months, and timeframes."""
    if not mt5.initialize():
        last_err = mt5.last_error()
        raise RuntimeError(f"Gagal menghubungkan ke MetaTrader 5: {last_err}")

    try:
        active_symbol = resolve_symbol(symbol)
        info = mt5.symbol_info(active_symbol)
        spread = info.spread if info else "?"
        logger.info(
            "Terhubung ke MT5. Simbol aktif: %s (Spread: %s pts)",
            active_symbol,
            spread,
        )

        now_utc = datetime.now(timezone.utc)
        current_year = now_utc.year
        current_month = now_utc.month

        stats: dict[str, Any] = {
            "symbol": active_symbol,
            "saved": 0,
            "skipped": 0,
            "unavailable": 0,
            "drifted": 0,
            "total_bars": 0,
            "by_tf": {tf: {"saved": 0, "bars": 0, "months": []} for tf in timeframes},
        }

        cache_dir.mkdir(parents=True, exist_ok=True)

        for tf_str in timeframes:
            tf_upper = tf_str.upper()
            if tf_upper not in TIMEFRAME_MAP:
                logger.warning("Timeframe %s tidak didukung, lewati.", tf_str)
                continue

            mt5_tf = TIMEFRAME_MAP[tf_upper]
            tf_lower = tf_upper.lower()
            logger.info("==================================================")
            logger.info("Memulai Ingestion Timeframe: %s", tf_upper)
            logger.info("==================================================")

            for year in range(start_year, end_year + 1):
                max_month = current_month if year == current_year else 12
                for month in range(1, max_month + 1):
                    file_name = f"{tf_lower}_{year}_{month:02d}.parquet"
                    target_file = cache_dir / file_name

                    # Check if already present, valid, and contains standard 'time' column
                    if target_file.exists() and not force:
                        try:
                            import polars as pl

                            schema_cols = set(
                                pl.scan_parquet(target_file).collect_schema().names()
                            )
                            # Only a fully contract-conformant file may be
                            # skipped. Checking `time` alone let 33 tick-derived
                            # files (no tick_volume/spread/real_volume, plus a
                            # stray __index_level_0__) sit in the cache forever
                            # while silently zeroing every volume in the chart.
                            drift = [
                                c for c in CONTRACT_COLUMNS if c not in schema_cols
                            ]
                            drift += [
                                c for c in schema_cols if c not in CONTRACT_COLUMNS
                            ]
                            if drift:
                                # Do NOT re-download: several months were built
                                # from tick parquet and their mid-price OHLC is
                                # pinned by the published benchmark. Overwriting
                                # them with broker rates would shift every price
                                # by half a spread. The repair script preserves
                                # OHLC; a re-download does not.
                                stats["drifted"] += 1
                                logger.error(
                                    "SKIP %s: skema menyimpang (%s). Perbaiki dengan "
                                    "`python scripts/repair_bar_cache_schema.py` - "
                                    "mengunduh ulang akan mengubah harga OHLC.",
                                    file_name,
                                    ", ".join(sorted(drift)),
                                )
                                continue
                            row_count = (
                                pl.scan_parquet(target_file)
                                .select(pl.len())
                                .collect()
                                .item()
                            )
                            if row_count > 10:
                                stats["skipped"] += 1
                                stats["by_tf"][tf_upper]["bars"] += row_count
                                stats["by_tf"][tf_upper]["months"].append(
                                    f"{year}-{month:02d}"
                                )
                                continue
                        except Exception:
                            logger.warning(
                                "File korup terdeteksi: %s, mengunduh ulang...",
                                file_name,
                            )

                    start_dt, end_dt = month_bounds(year, month)
                    rates = fetch_month_rates(active_symbol, mt5_tf, start_dt, end_dt)

                    if not is_valid_month_data(rates, start_dt, end_dt):
                        stats["unavailable"] += 1
                        # If M5 or M15 has no data in older years, log once per year
                        if month == 1:
                            logger.info(
                                "  [%s] %d-%02d: Data tidak tersedia di broker (riwayat belum ada).",
                                tf_upper,
                                year,
                                month,
                            )
                        continue

                    bar_count = save_rates_parquet(rates, target_file)
                    stats["saved"] += 1
                    stats["total_bars"] += bar_count
                    stats["by_tf"][tf_upper]["saved"] += 1
                    stats["by_tf"][tf_upper]["bars"] += bar_count
                    stats["by_tf"][tf_upper]["months"].append(f"{year}-{month:02d}")
                    logger.info(
                        "  [%s] Tersimpan: %s (%d bars)", tf_upper, file_name, bar_count
                    )

        return stats

    finally:
        mt5.shutdown()
        logger.info("Koneksi MT5 ditutup secara aman.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download 10-Year Historical Bars from MT5"
    )
    parser.add_argument(
        "--symbol", default=None, help="Symbol name (e.g. XAUUSD, XAUUSDm)"
    )
    parser.add_argument(
        "--start-year", type=int, default=2017, help="Start year (default 2017)"
    )
    parser.add_argument(
        "--end-year", type=int, default=2026, help="End year (default 2026)"
    )
    parser.add_argument(
        "--timeframes",
        default="H1,M15,M5",
        help="Comma-separated timeframes (default: H1,M15,M5)",
    )
    parser.add_argument(
        "--cache-dir", default="data/cache_bars", help="Target cache directory"
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing cache files"
    )
    args = parser.parse_args()

    tfs = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]
    cache_path = Path(args.cache_dir)

    t0 = time.time()
    stats = download_history(
        symbol=args.symbol,
        start_year=args.start_year,
        end_year=args.end_year,
        timeframes=tfs,
        cache_dir=cache_path,
        force=args.force,
    )
    duration = time.time() - t0

    print("\n" + "=" * 60)
    print("RINGKASAN INGESTION DATA 10 TAHUN (T-PAR-01)")
    print("=" * 60)
    print(f"Simbol:          {stats['symbol']}")
    print(f"Total File Baru: {stats['saved']}")
    print(f"File Dilewati:   {stats['skipped']} (Sudah ada di cache)")
    if stats["drifted"]:
        print(
            f"File DRIFT:      {stats['drifted']} (Skema menyimpang, TIDAK diunduh ulang)"
        )
        print("                 -> jalankan: python scripts/repair_bar_cache_schema.py")
    print(f"Total Bar:       {stats['total_bars']:,}")
    print(f"Waktu Proses:    {duration:.2f} detik")
    print("-" * 60)
    for tf, tf_stat in stats["by_tf"].items():
        m_list = tf_stat["months"]
        range_str = f"{m_list[0]} s/d {m_list[-1]}" if m_list else "Tidak ada"
        print(
            f"Timeframe {tf:<4}: {tf_stat['bars']:>10,} bars ({len(m_list):>3} bulan: {range_str})"
        )
    print("=" * 60 + "\n")
    # A drifted file is a silent data-quality failure downstream, so surface it
    # in the exit code instead of letting it look like a clean run.
    return 1 if stats["drifted"] else 0


if __name__ == "__main__":
    sys.exit(main())
