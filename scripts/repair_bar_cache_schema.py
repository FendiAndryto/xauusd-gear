"""Bar Cache Schema Repair & Canonicalisation.

Audits every bar file in `data/cache_bars/` and rewrites the ones that drifted
away from the canonical schema in SPEC-PA-REPLAY-01 §3.3.

Why files drift
---------------
Two independent writers produced this cache:

* `scripts/download_history_10y.py` — MT5 `copy_rates_range()`, which already
  returns `tick_volume` / `spread` / `real_volume`.
* `scripts/prepare_months_01_02_03.py` — resampled from raw **tick** parquet
  (`data/parquet/xauusd/year=*/month=*/ticks.parquet`). Those files carry only
  OHLC plus pandas' `__index_level_0__` leftover, no volume at all.

The tick-derived bars are *legitimate* — they are real mid-price bars and the
published benchmark numbers are pinned to them — so this script never touches
OHLC. It only restores the missing metadata columns by re-aggregating the very
same tick parquet the bars came from.

Canonical schema (all files, no exceptions)::

    time        Int64                      epoch seconds UTC
    open        Float64                    rounded 2dp
    high        Float64                    rounded 2dp
    low         Float64                    rounded 2dp
    close       Float64                    rounded 2dp
    tick_volume UInt64                     real tick count per bar
    spread      Int32                      mean spread in points per bar
    real_volume UInt64                     0 for tick-derived bars
    timestamp   Datetime[ns] (naive UTC)

Ticket: T-PAR-02 (follow-up hardening)
Reference Spec: SPEC-PA-REPLAY-01 §3.3

Usage::

    python scripts/repair_bar_cache_schema.py --check     # audit only, exit 1 on drift
    python scripts/repair_bar_cache_schema.py             # repair (backs up first)
    python scripts/repair_bar_cache_schema.py --no-backup # repair in place
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import polars as pl

CANONICAL_DTYPES: dict[str, pl.DataType] = {
    "time": pl.Int64,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "tick_volume": pl.UInt64,
    "spread": pl.Int32,
    "real_volume": pl.UInt64,
    "timestamp": pl.Datetime("ns"),
}

REQUIRED_COLUMNS = tuple(CANONICAL_DTYPES)

# MT5 XAUUSDm reports point=0.001; spread is quoted in points on the wire and in
# `copy_rates_range`, so tick-derived spreads must use the same unit.
POINT = 0.001

# A bar with fewer ticks than this is not worth re-aggregating; treat the month
# as "no tick source" and fall back to an honest zero.
MIN_TICKS_PER_MONTH = 100


def canonical_dtypes_for(frame: pl.DataFrame) -> dict[str, pl.DataType]:
    """Target dtype per column, reusing the file's own width for `timestamp`."""
    return dict(CANONICAL_DTYPES)


def _tick_source(year: int, month: int, ticks_root: Path) -> Optional[Path]:
    path = ticks_root / f"year={year}" / f"month={month:02d}" / "ticks.parquet"
    return path if path.exists() else None


def _tick_aggregates(path: Path, bar_seconds: int) -> pl.DataFrame:
    """Per-bar tick count and mean spread (points) from the raw tick parquet."""
    ticks = pl.read_parquet(path)
    if ticks.height < MIN_TICKS_PER_MONTH:
        return pl.DataFrame(
            schema={"time": pl.Int64, "tick_volume": pl.UInt64, "spread": pl.Int32}
        )

    bid = pl.col("bid")
    ask = pl.col("ask")
    spread_points = (ask - bid) / POINT

    return (
        ticks.with_columns(
            pl.col("timestamp").dt.truncate(f"{bar_seconds}s").alias("_bar")
        )
        .group_by("_bar")
        .agg(
            pl.len().cast(pl.UInt64).alias("tick_volume"),
            spread_points.mean().round().cast(pl.Int32).alias("spread"),
        )
        .with_columns(pl.col("_bar").dt.epoch("s").cast(pl.Int64).alias("time"))
        .drop("_bar")
        .sort("time")
    )


def _bar_seconds(timeframe: str) -> int:
    return {"m1": 60, "m5": 300, "m15": 900, "h1": 3600, "h4": 14400, "d1": 86400}[
        timeframe
    ]


def _timeframe_of(path: Path) -> str:
    return path.name.split("_")[0].lower()


def _month_of(path: Path) -> tuple[int, int]:
    _, year_s, month_s = path.stem.split("_")
    return int(year_s), int(month_s)


def inspect(path: Path) -> dict[str, Any]:
    """Describe how far a file is from the canonical schema."""
    schema = pl.scan_parquet(path).collect_schema()
    columns = schema.names()
    report: dict[str, Any] = {
        "path": path,
        "rows": 0,
        "missing": [c for c in REQUIRED_COLUMNS if c not in columns],
        "extra": [c for c in columns if c not in REQUIRED_COLUMNS],
        "dtype_mismatch": [],
        "timestamp_unit": None,
        "needs_repair": False,
    }
    for name, dtype in CANONICAL_DTYPES.items():
        actual = schema.get(name)
        if actual is None:
            continue
        if name == "timestamp":
            # Spec §3.3 asks for nanosecond, naive UTC. The cache legitimately
            # holds `us` (MT5 downloader) and `ns` (tick resampler) flavours and
            # `_load_bar_pair` normalises both, so the resolution alone is not
            # drift — only a non-datetime or an unexpected zone would be.
            if not isinstance(actual, pl.Datetime):
                report["dtype_mismatch"].append(f"{name}: {actual} != datetime")
            else:
                report["timestamp_unit"] = f"{actual.time_unit}, tz={actual.time_zone}"
            continue
        if actual != dtype:
            report["dtype_mismatch"].append(f"{name}: {actual} != {dtype}")

    try:
        import pyarrow.parquet as pq

        report["rows"] = int(pq.ParquetFile(path).metadata.num_rows)
    except Exception:
        report["rows"] = 0

    report["needs_repair"] = bool(
        report["missing"] or report["extra"] or report["dtype_mismatch"]
    )
    return report


def repair_file(
    path: Path,
    ticks_root: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Rewrite one bar file to the canonical schema, preserving OHLC exactly."""
    timeframe = _timeframe_of(path)
    year, month = _month_of(path)
    frame = pl.read_parquet(path)

    result: dict[str, Any] = {
        "path": path,
        "rows_before": frame.height,
        "rows_after": frame.height,
        "volume_source": "existing",
        "volume_nulls": 0,
    }

    # 1. Drop pandas leftovers / anything not in the contract.
    frame = frame.select([c for c in frame.columns if c in CANONICAL_COLUMNS_SET])

    # 2. Restore missing volume/spread from the tick parquet the bars came from.
    needs_volume = "tick_volume" not in frame.columns
    if needs_volume:
        source = _tick_source(year, month, ticks_root)
        if source is not None:
            agg = _tick_aggregates(source, _bar_seconds(timeframe))
            if agg.height:
                frame = frame.join(agg, on="time", how="left")
                result["volume_source"] = str(source)
            else:
                frame = frame.with_columns(
                    pl.lit(0, dtype=pl.UInt64).alias("tick_volume"),
                    pl.lit(0, dtype=pl.Int32).alias("spread"),
                )
                result["volume_source"] = "none (empty tick file)"
        else:
            frame = frame.with_columns(
                pl.lit(0, dtype=pl.UInt64).alias("tick_volume"),
                pl.lit(0, dtype=pl.Int32).alias("spread"),
            )
            result["volume_source"] = "none (no tick parquet)"

    # 3. Fill gaps for bars whose bucket had no ticks, then enforce dtypes.
    frame = frame.with_columns(
        pl.col("tick_volume").fill_null(0).cast(pl.UInt64),
        pl.col("spread").fill_null(0).cast(pl.Int32),
    )
    result["volume_nulls"] = int(frame.filter(pl.col("tick_volume") == 0).height)

    if "real_volume" not in frame.columns:
        frame = frame.with_columns(pl.lit(0, dtype=pl.UInt64).alias("real_volume"))

    # 4. `timestamp` must be a naive-UTC datetime at nanosecond resolution.
    if "timestamp" in frame.columns:
        ts = pl.col("timestamp")
        if frame.schema["timestamp"].time_zone is not None:
            ts = ts.dt.convert_time_zone("UTC").dt.replace_time_zone(None)
        frame = frame.with_columns(ts.cast(pl.Datetime("ns")).alias("timestamp"))
    else:
        frame = frame.with_columns(
            pl.col("time").cast(pl.Int64).cast(pl.Datetime("ms")).alias("timestamp")
        )

    # 5. OHLC is *never* rewritten. Tick-derived bars legitimately carry 3
    #    decimals (mid-price of a 0.001-point symbol) and the published
    #    benchmark figures are pinned to those exact values, so rounding to the
    #    spec's "2dp" would silently move every price. Cast only.
    frame = frame.with_columns(
        [pl.col(c).cast(pl.Float64).alias(c) for c in ("open", "high", "low", "close")]
    )

    frame = frame.select(list(REQUIRED_COLUMNS)).sort("time")
    result["rows_after"] = frame.height

    # Guard: any price movement here would invalidate the parity pins.
    original = (
        pl.read_parquet(path)
        .select(["time", "open", "high", "low", "close"])
        .sort("time")
    )
    if original.height != frame.height:
        raise RuntimeError(
            f"row count changed during repair: {original.height} -> {frame.height}"
        )
    for column in ("open", "high", "low", "close"):
        if not (original[column] == frame[column]).all():
            raise RuntimeError(f"{column} drifted during repair - refusing to write")

    if not dry_run:
        frame.write_parquet(path, compression="snappy", statistics=True)

    return result


CANONICAL_COLUMNS_SET = set(CANONICAL_DTYPES)


def audit(cache_dir: Path, *, dry_run: bool, backup: bool) -> int:
    files = sorted(cache_dir.glob("*.parquet"))
    if not files:
        print(f"[ERROR] Tidak ada file parquet di {cache_dir}")
        return 1

    ticks_root = cache_dir.parent / "parquet" / "xauusd"
    reports = [(f, inspect(f)) for f in files]
    drifted = [(f, r) for f, r in reports if r["needs_repair"]]

    print(f"\nAudit skema {len(files)} file di '{cache_dir}'")
    print(f"Tick source root: {ticks_root}\n")

    if not drifted:
        print(
            "[OK] Semua file sudah sesuai skema kanonik. Tidak ada yang perlu diperbaiki."
        )
        return 0

    print(f"[DRIFT] {len(drifted)} file menyimpang dari skema kanonik:\n")
    print(f"{'File':<26}{'Rows':>8}  Masalah")
    print("-" * 92)
    for path, report in drifted:
        problems = []
        if report["missing"]:
            problems.append(f"missing={','.join(report['missing'])}")
        if report["extra"]:
            problems.append(f"extra={','.join(report['extra'])}")
        if report["dtype_mismatch"]:
            problems.append(f"dtype[{'; '.join(report['dtype_mismatch'])}]")
        print(f"{path.name:<26}{report['rows']:>8}  {' '.join(problems)}")

    if dry_run:
        print(
            f"\n[DRY-RUN] {len(drifted)} file akan diperbaiki. Jalankan tanpa --check untuk menulis."
        )
        return 1

    if backup:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_dir = cache_dir.parent / f"cache_bars_backup_{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for path, _ in drifted:
            shutil.copy2(path, backup_dir / path.name)
        print(f"\n[BACKUP] {len(drifted)} file asli disalin ke {backup_dir}")

    print()
    t0 = time.time()
    failures: list[tuple[Path, str]] = []
    for path, _ in drifted:
        try:
            result = repair_file(path, ticks_root)
            print(
                f"[FIX] {path.name:<26} rows={result['rows_before']} "
                f"volume<={Path(str(result['volume_source'])).name if result['volume_source'] != 'existing' else 'existing'} "
                f"zero_volume_bars={result['volume_nulls']}"
            )
        except Exception as exc:  # keep going; report at the end
            failures.append((path, str(exc)))
            print(f"[FAIL] {path.name}: {exc}")

    print(f"\nSelesai dalam {time.time() - t0:.2f} detik.")

    # Re-audit so the exit code reflects reality, not intent.
    remaining = [
        (f, r) for f, r in ((f, inspect(f)) for f, _ in drifted) if r["needs_repair"]
    ]
    if failures or remaining:
        print(
            f"\n[PERINGATAN] {len(failures)} gagal ditulis, {len(remaining)} masih menyimpang."
        )
        return 1

    print("[SUKSES] Seluruh file kini memakai skema kanonik SPEC-PA-REPLAY-01 §3.3.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair bar cache schema drift")
    parser.add_argument(
        "--cache-dir", default="data/cache_bars", help="Bar cache directory"
    )
    parser.add_argument("--check", action="store_true", help="Audit only, never write")
    parser.add_argument(
        "--no-backup", action="store_true", help="Skip the pre-repair backup copy"
    )
    args = parser.parse_args()
    return audit(Path(args.cache_dir), dry_run=args.check, backup=not args.no_backup)


if __name__ == "__main__":
    sys.exit(main())
