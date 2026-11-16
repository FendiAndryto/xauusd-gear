"""Tests for the pure price action catalogue & payload (T-PAR-06 / T-PAR-07).

The replay terminal asks two questions: *what periods exist for this timeframe*
and *give me those candles*. Both answers used to be wrong in ways nothing
caught:

* the catalogue advertised "H1 from 2018-07" when those files actually hold ~26
  **daily** bars per month, so "H1 2019" was 27 candles of a 480-candle month;
* the payload was only reachable through the strategy/session machinery, so an
  H1 month without an M15 sibling could not be replayed at all.

These tests pin: honest coverage (usable vs sparse), every period mode, the
candles-only shape, price precision, and the day-granular trim.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from fastapi import HTTPException

from src.assistant import replay_api, replay_engine

BAR_SECONDS = {"m1": 60, "m5": 300, "m15": 900, "h1": 3600}


def _month_start_epoch(year: int, month: int) -> int:
    import datetime as dt

    return int(dt.datetime(year, month, 1, tzinfo=dt.timezone.utc).timestamp())


def _write_month(
    cache: Path,
    kind: str,
    year: int,
    month: int,
    bars: int,
    *,
    start_epoch: int | None = None,
) -> Path:
    """Write a synthetic month file with the canonical §3.3 schema."""
    step = BAR_SECONDS[kind]
    first = _month_start_epoch(year, month) if start_epoch is None else start_epoch
    times = [first + i * step for i in range(bars)]
    base = 2000.0
    frame = pl.DataFrame(
        {
            "time": times,
            "open": [base + i * 0.001 for i in range(bars)],
            "high": [base + i * 0.001 + 0.5 for i in range(bars)],
            "low": [base + i * 0.001 - 0.5 for i in range(bars)],
            "close": [base + i * 0.001 + 0.25 for i in range(bars)],
            "tick_volume": [100 + i for i in range(bars)],
            "spread": [240] * bars,
            "real_volume": [0] * bars,
            "timestamp": [None] * bars,
        }
    ).with_columns(pl.col("time").cast(pl.Datetime("ns")).alias("timestamp"))
    path = cache / f"{kind}_{year}_{month:02d}.parquet"
    frame.write_parquet(path)
    return path


@pytest.fixture()
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Synthetic cache with a dense and a sparse era, wired into the engine."""
    root = tmp_path / "cache_bars"
    root.mkdir()

    # M5: two adjacent months.
    _write_month(root, "m5", 2026, 9, 2000)
    _write_month(root, "m5", 2026, 10, 2000)

    # H1: one dense month and one "daily bars in an hourly file" month.
    _write_month(root, "h1", 2026, 10, 480)
    _write_month(root, "h1", 2019, 1, 27)

    # A decoy that must never be parsed as a month file.
    (root / "notes_2026_10.parquet").write_bytes(b"not parquet")

    monkeypatch.setattr(replay_engine, "CACHE_DIR", root)
    replay_engine._SCAN_CACHE.clear()
    replay_engine.clear_pure_cache()
    yield root
    replay_engine._SCAN_CACHE.clear()
    replay_engine.clear_pure_cache()


# ----------------------------------------------------------------- discovery


def test_scan_reports_every_timeframe_and_ignores_decoys(cache: Path) -> None:
    files = replay_engine.scan_timeframe_files()

    assert [m.key for m in files["M5"]] == [(2026, 9), (2026, 10)]
    assert [m.key for m in files["H1"]] == [(2019, 1), (2026, 10)]
    assert files["M15"] == [] and files["M1"] == []


def test_sparse_month_is_detected_and_usable_start_is_honest(cache: Path) -> None:
    files = replay_engine.scan_timeframe_files()

    assert replay_engine.sparse_months(files, "H1") == {(2019, 1)}

    coverage = replay_engine.timeframe_coverage(files, cache)
    h1 = coverage["H1"]
    assert h1["start_date"] == "2019-01-01"
    # The honest hourly start, not the oldest file on disk.
    assert h1["usable_start_date"] == "2026-10-01"
    assert h1["sparse_months"] == ["2019-01"]
    assert h1["available_months"] == ["2019-01", "2026-10"]
    assert coverage["M5"]["available_months"] == ["2026-09", "2026-10"]
    assert coverage["M5"]["sparse_months"] == []


def test_available_years_union(cache: Path) -> None:
    assert replay_engine.available_years() == [2019, 2026]


# -------------------------------------------------------------- period modes


def test_resolve_month_and_year(cache: Path) -> None:
    month = replay_engine.resolve_period("M5", "month", year=2026, month=10)
    assert [m.key for m in month] == [(2026, 10)]

    year = replay_engine.resolve_period("M5", "year", year=2026)
    assert [m.key for m in year] == [(2026, 9), (2026, 10)]


def test_resolve_requires_arguments(cache: Path) -> None:
    with pytest.raises(replay_engine.ReplaySessionError, match="butuh year dan month"):
        replay_engine.resolve_period("M5", "month", year=2026)
    with pytest.raises(replay_engine.ReplaySessionError, match="butuh start_date"):
        replay_engine.resolve_period("M5", "custom")


def test_resolve_rejects_unknown_timeframe_and_mode(cache: Path) -> None:
    with pytest.raises(
        replay_engine.ReplaySessionError, match="Timeframe tidak dikenal"
    ):
        replay_engine.resolve_period("H4", "month", year=2026, month=10)
    with pytest.raises(
        replay_engine.ReplaySessionError, match="period_mode tidak dikenal"
    ):
        replay_engine.resolve_period("M5", "weekly")


def test_missing_month_error_names_the_real_coverage(cache: Path) -> None:
    with pytest.raises(replay_engine.ReplaySessionError) as exc:
        replay_engine.resolve_period("M5", "month", year=2019, month=1)

    message = str(exc.value)
    assert "Tidak ada data M5 pada Januari 2019" in message
    assert "2026-09-01" in message and "2026-10" in message


def test_empty_range_for_timeframe_with_no_files(cache: Path) -> None:
    with pytest.raises(replay_engine.ReplaySessionError, match="belum punya data"):
        replay_engine.resolve_period("M1", "month", year=2026, month=10)


def test_custom_range_includes_partial_edge_months(cache: Path) -> None:
    # 2026-09-20 .. 2026-10-05 must pull in both months, not just October.
    months = replay_engine.resolve_period(
        "M5", "custom", start_date=date(2026, 9, 20), end_date=date(2026, 10, 5)
    )
    assert [m.key for m in months] == [(2026, 9), (2026, 10)]


# ------------------------------------------------------------------ payload


def test_payload_is_candles_and_meta_only(cache: Path) -> None:
    payload = replay_engine.generate_pure_payload("M5", "month", year=2026, month=10)

    assert set(payload) == {"meta", "candles"}
    meta = payload["meta"]
    assert meta["timeframe"] == "M5"
    assert meta["total_bars"] == 2000
    assert meta["period_label"] == "Oktober 2026"
    assert meta["start_date"] == "2026-10-01"
    # 2000 bars x 5 min ≈ 6.9 days, so the month's synthetic data ends on the 7th.
    assert meta["end_date"] == "2026-10-07"
    assert meta["warnings"] == []
    assert set(payload["candles"][0]) == {
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }


def test_payload_preserves_source_precision(cache: Path) -> None:
    payload = replay_engine.generate_pure_payload("M5", "month", year=2026, month=10)
    candle = payload["candles"][0]

    # 2000.000 must stay 2000.0, but the third decimal of later bars must survive:
    # rounding to 2dp is what silently moved every tick-derived price.
    assert payload["candles"][1]["open"] == 2000.001
    assert candle["volume"] == 100.0


def test_payload_cache_returns_the_same_object(cache: Path) -> None:
    first = replay_engine.generate_pure_payload("M5", "month", year=2026, month=10)
    second = replay_engine.generate_pure_payload("M5", "month", year=2026, month=10)

    assert first is second


def test_sparse_month_payload_carries_a_warning(cache: Path) -> None:
    payload = replay_engine.generate_pure_payload("H1", "month", year=2019, month=1)

    assert payload["meta"]["total_bars"] == 27
    warnings = payload["meta"]["warnings"]
    assert len(warnings) == 1
    assert "27 bar H1" in warnings[0]
    assert "2026-10-01" in warnings[0]


def test_custom_payload_is_trimmed_to_the_day(cache: Path) -> None:
    payload = replay_engine.generate_pure_payload(
        "H1", "custom", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1)
    )

    # 24 hourly bars in a day, and nothing from neighbouring days.
    assert payload["meta"]["total_bars"] == 24
    assert payload["meta"]["start_date"] == payload["meta"]["end_date"] == "2026-10-01"


# ---------------------------------------------------------------------- API
#
# `replay_data` is a FastAPI handler, so calling it directly leaves `Query(...)`
# sentinels in every unnamed parameter. This shim supplies the HTTP defaults so
# the tests exercise the routing logic rather than FastAPI's module import order.
def _data(**overrides):
    call = {
        "session_id": None,
        "strategy": "mode_a_pure",
        "rr_ratio": replay_engine.DEFAULT_RR,
        "start_date": None,
        "end_date": None,
        "period_mode": None,
        "timeframe": None,
        "year": None,
        "month": None,
    }
    call.update(overrides)
    return replay_api.replay_data(**call)


def test_catalogue_exposes_coverage_alongside_legacy_keys(cache: Path) -> None:
    catalogue = replay_api.replay_sessions()

    for legacy in ("sessions", "default_session_id", "strategies", "rr_presets"):
        assert legacy in catalogue, f"legacy UI key {legacy} disappeared"
    assert catalogue["timeframes"] == ["M5", "H1"]
    assert catalogue["available_years"] == [2019, 2026]
    assert catalogue["timeframe_coverage"]["H1"]["usable_start_date"] == "2026-10-01"
    assert catalogue["default_selection"] == {
        "period_mode": "month",
        "year": 2026,
        "month": 10,
        "timeframe": "M5",
    }


def test_data_endpoint_returns_pure_payload_when_period_mode_given(cache: Path) -> None:
    payload = _data(period_mode="month", timeframe="M5", year=2026, month=10)

    assert set(payload) == {"meta", "candles"}
    assert payload["meta"]["months_loaded"] == 1


def test_data_endpoint_maps_missing_data_to_404(cache: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        _data(period_mode="month", timeframe="M5", year=2019, month=1)

    assert exc.value.status_code == 404
    assert "Tidak ada data M5" in exc.value.detail


def test_data_endpoint_rejects_bad_dates(cache: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        _data(period_mode="custom", timeframe="M5", start_date="10-05-2026")

    assert exc.value.status_code == 400
    assert "YYYY-MM-DD" in exc.value.detail


def test_data_endpoint_legacy_shape_is_untouched(cache: Path) -> None:
    """No `period_mode` => the benchmark-parity payload still answers.

    The strategy needs an M15/M5 pair, which this synthetic cache does not have,
    so the engine refuses with a session error and the API turns it into a 404 —
    the important part is that it never silently switches to the pure shape.
    """
    with pytest.raises(HTTPException) as exc:
        _data(session_id="does_not_exist")

    assert exc.value.status_code == 404
    assert "tidak dikenal" in exc.value.detail
