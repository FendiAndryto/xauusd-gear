"""Unit tests for microstructure profiler."""

from datetime import datetime, timezone
import polars as pl
import pytest

from src.analytics.microstructure import MicrostructureProfiler
from src.ingestion.schema import TICK_SCHEMA


def test_microstructure_profiler():
    df = pl.DataFrame({
        "timestamp": [
            datetime(2026, 10, 1, 13, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 10, 1, 13, 0, 1, 0, tzinfo=timezone.utc),
            datetime(2026, 10, 1, 21, 0, 0, 0, tzinfo=timezone.utc),
        ],
        "bid": [2650.00, 2650.10, 2650.00],
        "ask": [2650.24, 2650.34, 2650.60],
        "spread": [0.24, 0.24, 0.60],
        "volume": [1.0, 1.0, 1.0],
        "flags": [6, 6, 6],
    }).cast(TICK_SCHEMA)

    profiler = MicrostructureProfiler()
    profiles = profiler.profile(df)

    assert len(profiles) == 2  # hour 13 and hour 21
    p13 = [p for p in profiles if p.hour_utc == 13][0]
    p21 = [p for p in profiles if p.hour_utc == 21][0]

    assert p13.hour_wib == 20
    assert p13.median_spread == 0.240
    assert p21.trading_regime == "AVOID_ROLLOVER"
