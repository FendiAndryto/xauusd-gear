"""Contract tests for the bar cache schema (SPEC-PA-REPLAY-01 §3.3).

Why these exist
---------------
33 of the 179 cached bar files were silently produced from raw tick parquet
instead of MT5 rates. They were readable and their OHLC was correct, so nothing
failed — but `tick_volume` / `spread` / `real_volume` were absent and
`replay_engine._candle_rows` quietly substituted `0.0` for the volume of every
bar. The chart drew a flat volume pane for all of 2026 and no test noticed.

These tests pin the three properties that make that class of bug impossible to
reintroduce unnoticed:

1. `inspect()`/`verify_file()` must *reject* a file missing contract columns.
2. `repair_file()` must restore the missing metadata from the tick parquet
   without moving a single OHLC value (the published benchmark parity depends
   on those exact prices).
3. All three scripts must agree on what the contract is.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest

from scripts import repair_bar_cache_schema as repair
from scripts import verify_parquet_cache as verify

OHLC = ("open", "high", "low", "close")
CONTRACT = (
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

# 2026-01-01 23:05:00 UTC, aligned to a 5-minute boundary.
BASE_EPOCH = 1767308700
BAR_SECONDS = 300
POINT = 0.001


def _legacy_bars(times: list[int]) -> pl.DataFrame:
    """A tick-derived bar file exactly as `prepare_months_01_02_03.py` wrote it.

    No volume columns, a pandas `__index_level_0__` leftover, and a tz-aware
    millisecond `timestamp`.
    """
    stamped = (
        pl.Series("time", times).cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    )
    return pl.DataFrame(
        {
            "time": times,
            "open": [4151.117, 4151.644],
            "high": [4151.900, 4152.800],
            "low": [4150.900, 4151.100],
            "close": [4151.600, 4152.500],
            "timestamp": stamped,
            "__index_level_0__": stamped,
        }
    )


def _synthetic_ticks() -> pl.DataFrame:
    """60 ticks in each of two 5-minute buckets, so volume is unambiguous."""
    start = datetime(2026, 1, 1, 23, 5, tzinfo=timezone.utc)
    stamps: list[datetime] = []
    for bucket in range(2):
        for i in range(60):
            stamps.append(
                start + timedelta(seconds=BAR_SECONDS * bucket, microseconds=i * 1000)
            )
    return pl.DataFrame(
        {
            "timestamp": stamps,
            "bid": [2000.0] * len(stamps),
            "ask": [2000.0 + 240 * POINT] * len(stamps),
            "flags": [134] * len(stamps),
        }
    )


@pytest.fixture()
def cache(tmp_path: Path) -> tuple[Path, Path]:
    """A one-file cache plus the tick parquet the bars were derived from."""
    cache_dir = tmp_path / "cache_bars"
    cache_dir.mkdir()
    ticks_dir = tmp_path / "parquet" / "xauusd" / "year=2026" / "month=01"
    ticks_dir.mkdir(parents=True)

    _synthetic_ticks().write_parquet(ticks_dir / "ticks.parquet")
    bar_file = cache_dir / "m5_2026_01.parquet"
    _legacy_bars([BASE_EPOCH, BASE_EPOCH + BAR_SECONDS]).write_parquet(bar_file)
    return bar_file, cache_dir.parent / "parquet" / "xauusd"


# ------------------------------------------------------------------- detection


def test_inspect_flags_tick_derived_file_as_drift(cache: tuple[Path, Path]) -> None:
    bar_file, _ = cache
    report = repair.inspect(bar_file)

    assert report["needs_repair"] is True
    assert set(report["missing"]) == {"tick_volume", "spread", "real_volume"}
    assert report["extra"] == ["__index_level_0__"]


def test_verify_file_rejects_drift_with_actionable_message(
    cache: tuple[Path, Path],
) -> None:
    bar_file, _ = cache
    result = verify.verify_file(bar_file)

    assert result["valid"] is False
    assert "3.3" in result["error"]
    assert "repair_bar_cache_schema" in result["error"]
    # The file is *readable*; only the contract is broken.
    assert result["bars"] == 2


# --------------------------------------------------------------------- repair


def test_repair_restores_volume_and_preserves_ohlc_bit_exactly(
    cache: tuple[Path, Path],
) -> None:
    bar_file, ticks_root = cache
    before = pl.read_parquet(bar_file)

    repair.repair_file(bar_file, ticks_root)

    after = pl.read_parquet(bar_file)
    assert tuple(after.columns) == CONTRACT
    assert after.height == before.height

    # The parity pins (`48 trades / 23.5% / 56.25%`) are computed from these
    # exact prices; any movement here is a silent strategy change.
    for column in OHLC:
        assert (after[column] == before[column]).all(), f"{column} moved during repair"

    assert after["tick_volume"].to_list() == [60, 60]
    assert after["spread"].to_list() == [240, 240]
    assert after["real_volume"].to_list() == [0, 0]

    timestamp = after.schema["timestamp"]
    assert isinstance(timestamp, pl.Datetime)
    assert timestamp.time_zone is None, "timestamp must be naive UTC"


def test_repair_is_idempotent_and_leaves_a_clean_audit(
    cache: tuple[Path, Path],
) -> None:
    bar_file, ticks_root = cache
    repair.repair_file(bar_file, ticks_root)
    snapshot = pl.read_parquet(bar_file)

    assert repair.inspect(bar_file)["needs_repair"] is False
    assert verify.verify_file(bar_file)["valid"] is True

    repair.repair_file(bar_file, ticks_root)
    assert pl.read_parquet(bar_file).equals(snapshot), "second repair changed the file"


# ----------------------------------------------------------------- consistency


def test_scripts_agree_on_the_contract() -> None:
    """`inspect`, `verify_file` and the downloader's skip-logic share one list."""
    from scripts import download_history_10y as downloader

    assert verify.CONTRACT_COLUMNS == CONTRACT
    assert downloader.CONTRACT_COLUMNS == CONTRACT
    assert repair.REQUIRED_COLUMNS == CONTRACT
