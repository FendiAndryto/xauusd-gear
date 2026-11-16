"""Parquet Cache Integrity & Metadata Verifier.

Audits and verifies the integrity, schema, and OHLC consistency of all
cached Parquet bar files in `data/cache_bars/`.

Ticket: T-PAR-02
Reference Spec: SPEC-PA-REPLAY-01
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import polars as pl

# SPEC-PA-REPLAY-01 §3.3 canonical contract. A file that lacks any of these is
# not a valid cache member, even if its OHLC values are fine: downstream code
# (replay_engine._candle_rows, the replay chart volume pane) silently degrades
# to zeros when a column is absent, which is exactly how the 2026 tick-derived
# files went unnoticed for weeks.
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

# Minimum subset required to even compute OHLC/ordering checks.
REQUIRED_COLUMNS = {"time", "open", "high", "low", "close"}


def verify_file(file_path: Path) -> dict[str, Any]:
    """Verify single parquet file for schema, time monotonicity, and OHLC rules."""
    result: dict[str, Any] = {
        "path": file_path,
        "name": file_path.name,
        "valid": False,
        "bars": 0,
        "error": None,
        "start_time": None,
        "end_time": None,
        "size_bytes": file_path.stat().st_size,
        "schema_drift": [],
    }

    try:
        df = pl.read_parquet(file_path)
        result["bars"] = len(df)

        if len(df) == 0:
            result["error"] = "File kosong (0 bars)"
            return result

        cols = set(df.columns)
        missing = REQUIRED_COLUMNS - cols
        if missing:
            result["error"] = f"Kolom wajib hilang: {missing}"
            return result

        # Contract conformance: missing metadata columns, or pandas leftovers.
        drift = [c for c in CONTRACT_COLUMNS if c not in cols]
        drift += [f"extra:{c}" for c in df.columns if c not in CONTRACT_COLUMNS]
        result["schema_drift"] = drift
        if drift:
            result["error"] = (
                f"Skema menyimpang dari kontrak §3.3: {', '.join(drift)} "
                f"(jalankan scripts/repair_bar_cache_schema.py)"
            )
            return result

        # Check time monotonicity (strictly ascending)
        times = df["time"].to_numpy()
        diffs = times[1:] - times[:-1]
        if (diffs <= 0).any():
            bad_idx = int((diffs <= 0).argmax())
            result["error"] = (
                f"Timestamp tidak monotonik di bar index {bad_idx} ({times[bad_idx]} -> {times[bad_idx + 1]})"
            )
            return result

        # Check OHLC consistency
        opens = df["open"].to_numpy()
        highs = df["high"].to_numpy()
        lows = df["low"].to_numpy()
        closes = df["close"].to_numpy()

        bad_high = (highs < opens) | (highs < closes)
        if bad_high.any():
            result["error"] = (
                f"Inkonsistensi High < Open/Close pada bar index {int(bad_high.argmax())}"
            )
            return result

        bad_low = (lows > opens) | (lows > closes)
        if bad_low.any():
            result["error"] = (
                f"Inkonsistensi Low > Open/Close pada bar index {int(bad_low.argmax())}"
            )
            return result

        result["valid"] = True
        result["start_time"] = int(times[0])
        result["end_time"] = int(times[-1])
        return result

    except Exception as exc:
        result["error"] = f"Gagal membaca parquet: {exc}"
        return result


def audit_cache(cache_dir: Path) -> int:
    """Scan and verify all parquet files in cache_dir."""
    files = sorted(cache_dir.glob("*.parquet"))
    if not files:
        print(f"[ERROR] Tidak ada file parquet ditemukan di {cache_dir}")
        return 1

    print(
        f"\nMemulai audit integritas pada {len(files)} file parquet di '{cache_dir}'...\n"
    )

    tf_summary: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "files": 0,
            "bars": 0,
            "bytes": 0,
            "min_time": float("inf"),
            "max_time": float("-inf"),
        }
    )

    failures: list[dict[str, Any]] = []
    t0 = time.time()

    for path in files:
        res = verify_file(path)
        if not res["valid"]:
            failures.append(res)
            print(f"[FAIL] {res['name']}: {res['error']}")
            continue

        # Extract timeframe from filename prefix (e.g. 'm5_2026_10.parquet' -> 'M5')
        prefix = path.name.split("_")[0].upper()
        summary = tf_summary[prefix]
        summary["files"] += 1
        summary["bars"] += res["bars"]
        summary["bytes"] += res["size_bytes"]
        if res["start_time"] < summary["min_time"]:
            summary["min_time"] = res["start_time"]
        if res["end_time"] > summary["max_time"]:
            summary["max_time"] = res["end_time"]

    elapsed = time.time() - t0

    from datetime import datetime, timezone

    print("=" * 80)
    print("HASIL AUDIT INTEGRITAS CACHE PARQUET (T-PAR-02)")
    print("=" * 80)
    print(
        f"{'Timeframe':<10} | {'Files':<7} | {'Total Bars':>14} | {'Ukuran Disk':>12} | {'Rentang Tanggal':<32}"
    )
    print("-" * 80)

    total_all_bars = 0
    total_all_bytes = 0

    for tf in sorted(tf_summary.keys()):
        s = tf_summary[tf]
        total_all_bars += s["bars"]
        total_all_bytes += s["bytes"]
        start_str = datetime.fromtimestamp(s["min_time"], timezone.utc).strftime(
            "%Y-%m-%d"
        )
        end_str = datetime.fromtimestamp(s["max_time"], timezone.utc).strftime(
            "%Y-%m-%d"
        )
        range_str = f"{start_str}  s/d  {end_str}"
        size_mb = s["bytes"] / (1024 * 1024)
        print(
            f"{tf:<10} | {s['files']:<7} | {s['bars']:>14,} | {size_mb:>9.2f} MB | {range_str:<32}"
        )

    print("=" * 80)
    total_mb = total_all_bytes / (1024 * 1024)
    print(
        f"Total Keseluruhan: {total_all_bars:,} bars ({total_mb:.2f} MB) dalam {elapsed:.2f} detik."
    )

    if failures:
        print(f"\n[PERINGATAN] Ditemukan {len(failures)} file tidak valid atau korup:")
        for f in failures:
            print(f" - {f['name']}: {f['error']}")
        return 1

    print(
        "\n[SUKSES] Seluruh file Parquet lolos uji integritas (100% valid dan konsisten)!\n"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Parquet Cache Bars Integrity")
    parser.add_argument(
        "--cache-dir", default="data/cache_bars", help="Cache directory to audit"
    )
    args = parser.parse_args()
    return audit_cache(Path(args.cache_dir))


if __name__ == "__main__":
    sys.exit(main())
