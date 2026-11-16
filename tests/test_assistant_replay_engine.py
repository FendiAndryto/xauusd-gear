"""Regression tests for the visual replay data engine (tickets T-REP-01, T-REP-02).

The single most important property of this feature is that the replay must show
*exactly* the numbers the official benchmark report claims — otherwise the visual
tool teaches the user the wrong lesson about the strategy. These tests pin the
payload against the published report figures.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.assistant import replay_engine
from src.assistant.replay_api import replay_data, replay_sessions
from src.assistant.replay_engine import ReplaySessionError


@pytest.fixture(scope="module", autouse=True)
def _clear_cache():
    replay_engine.clear_cache()
    yield
    replay_engine.clear_cache()


def _api(**overrides):
    """Call the `/data` handler the way HTTP would.

    `replay_data` is a FastAPI handler, so any parameter the caller omits keeps its
    `Query(...)` sentinel. Since T-PAR-07 the handler branches on whether
    `period_mode` was supplied, and a sentinel would look like "supplied" — every
    legacy parity test would then be routed to the candles-only path. This shim
    passes the HTTP defaults so these tests keep pinning the legacy branch.
    """
    call = {
        "session_id": None,
        "strategy": "mode_a_pure",
        "rr_ratio": 1.5,
        "start_date": None,
        "end_date": None,
        "period_mode": None,
        "timeframe": None,
        "year": None,
        "month": None,
    }
    call.update(overrides)
    return replay_data(**call)


# ------------------------------------------------------------------ catalogue


def test_sessions_catalogue_lists_m5_and_m15_presets():
    data = replay_sessions()
    ids = [s["id"] for s in data["sessions"]]
    assert "m5_all" in ids
    assert "m15_all" in ids
    assert data["default_session_id"] == "m5_all"

    m5 = next(s for s in data["sessions"] if s["id"] == "m5_all")
    assert m5["timeframe"] == "M5"
    assert m5["macro_timeframe"] == "M15"
    assert m5["total_bars"] > 50_000
    assert m5["start_date"].startswith("2025-06")

    m15 = next(s for s in data["sessions"] if s["id"] == "m15_all")
    assert m15["timeframe"] == "M15"
    assert m15["macro_timeframe"] == "H1"


def test_every_session_is_single_timeframe_and_ordered():
    for session in replay_engine.build_sessions():
        assert session.months, session.id
        assert {m.ltf for m in session.months} == {session.timeframe}
        keys = [m.key for m in session.months]
        assert keys == sorted(keys)


def test_unknown_session_is_rejected():
    with pytest.raises(ReplaySessionError):
        replay_engine.get_session("tidak_ada")


# ---------------------------------------------------------------- parity pins


def test_month_payload_matches_published_report():
    """Oct 2026 row of LAPORAN_PENGUJIAN_MODE_A_MURNI.md: 48 trades, WR 56.2%."""
    payload = _api(
        session_id="m_2026_10",
        strategy="mode_a_pure",
        rr_ratio=1.5,
        start_date=None,
        end_date=None,
    )
    meta = payload["meta"]
    assert meta["total_bars"] == 6048
    assert meta["total_trades"] == 48
    assert meta["win_rate"] == pytest.approx(56.25, abs=0.05)
    assert meta["max_drawdown_pct"] == pytest.approx(4.33, abs=0.05)
    # Fresh month starts from $10k (no carryover).
    assert meta["initial_capital"] == 10_000.0
    assert meta["final_capital"] == pytest.approx(12_349.84, abs=0.01)


def test_m15_archive_ends_at_report_final_capital():
    """The report's Nov 2022 - May 2025 segment closes at $13,798.82."""
    payload = replay_engine.generate_replay_session("m15_all", "mode_a_pure", 1.5)
    assert payload["meta"]["final_capital"] == pytest.approx(13_798.82, abs=0.01)
    assert payload["meta"]["total_trades"] == 377


def test_trade_ledger_reconciles_to_the_cent():
    """HUD balance must never drift from the report by a rounding artefact.

    The runner carries full float precision, but the UI shows 2 decimals.
    Rounding pnl/equity_before/equity_after independently used to break the
    chain by +/-$0.01 per trade (9/48 breaks for Oct 2026), so the replayed
    balance disagreed with the official report.
    """
    for session_id in ("m_2026_10", "m15_all"):
        payload = replay_engine.generate_replay_session(session_id, "mode_a_pure", 1.5)
        trades = payload["trades"]
        meta = payload["meta"]

        for trade in trades:
            # Every published value is cent-exact...
            assert round(trade["pnl"], 2) == trade["pnl"], trade["trade_id"]
            assert round(trade["equity_before"], 2) == trade["equity_before"]
            assert round(trade["equity_after"], 2) == trade["equity_after"]
            # ...and the chain closes exactly.
            assert (
                pytest.approx(trade["equity_before"] + trade["pnl"], abs=1e-9)
                == trade["equity_after"]
            ), trade["trade_id"]

        # Consecutive trades chain without gaps.
        for previous, current in zip(trades, trades[1:]):
            assert (
                pytest.approx(previous["equity_after"], abs=1e-9)
                == current["equity_before"]
            )

        # Replaying every trade from the opening balance lands on the report.
        replayed = meta["initial_capital"] + sum(t["pnl"] for t in trades)
        assert pytest.approx(meta["final_capital"], abs=1e-9) == replayed

        # The equity curve ends on the same number.
        assert (
            pytest.approx(payload["equity_curve"][-1]["equity"], abs=0.01)
            == meta["final_capital"]
        )


# ------------------------------------------------------------ payload integrity


def test_candles_are_ordered_and_ohlc_consistent():
    payload = replay_engine.generate_replay_session("m_2026_10", "mode_a_pure", 1.5)
    candles = payload["candles"]
    times = [c["time"] for c in candles]
    assert times == sorted(times)
    assert len(set(times)) == len(times)
    for candle in candles:
        assert candle["low"] <= candle["open"] <= candle["high"]
        assert candle["low"] <= candle["close"] <= candle["high"]


def test_trade_indices_point_at_matching_bars():
    payload = replay_engine.generate_replay_session("m_2026_10", "mode_a_pure", 1.5)
    candles = payload["candles"]
    for trade in payload["trades"]:
        assert 0 <= trade["entry_idx"] < len(candles)
        assert trade["entry_idx"] <= trade["exit_idx"] < len(candles)
        assert candles[trade["entry_idx"]]["time"] == trade["entry_time"]
        assert candles[trade["exit_idx"]]["time"] == trade["exit_time"]
        assert trade["side"] in ("BUY", "SELL")
        assert trade["outcome"] in ("WIN", "LOSS", "EXPIRED")
        if trade["side"] == "BUY":
            assert trade["sl_price"] < trade["entry_price"] < trade["tp_price"]
        else:
            assert trade["tp_price"] < trade["entry_price"] < trade["sl_price"]


def test_equity_ladder_is_consistent_with_trade_pnl():
    payload = replay_engine.generate_replay_session("m_2026_10", "mode_a_pure", 1.5)
    previous = payload["meta"]["initial_capital"]
    for trade in payload["trades"]:
        # The ladder must chain exactly: no gaps, no double counting.
        assert trade["equity_before"] == pytest.approx(previous, abs=0.011)
        assert trade["equity_after"] == pytest.approx(
            trade["equity_before"] + trade["pnl"], abs=0.011
        )
        previous = trade["equity_after"]
    assert payload["meta"]["final_capital"] == pytest.approx(previous, abs=0.011)
    # ...and the ladder must land on the same capital the report publishes.
    assert payload["meta"]["final_capital"] == pytest.approx(12_349.84, abs=0.02)


def test_equity_curve_is_monotone_in_time_and_starts_at_initial_capital():
    payload = replay_engine.generate_replay_session("m_2026_10", "mode_a_pure", 1.5)
    curve = payload["equity_curve"]
    assert curve[0]["equity"] == payload["meta"]["initial_capital"]
    times = [p["time"] for p in curve]
    assert times == sorted(times)
    assert curve[-1]["equity"] == pytest.approx(
        payload["meta"]["final_capital"], abs=0.02
    )


def test_zones_bracket_their_trade_entry_price():
    payload = replay_engine.generate_replay_session("m_2026_10", "mode_a_pure", 1.5)
    trades = {t["trade_id"]: t for t in payload["trades"]}
    assert len(payload["zones"]) == len(payload["trades"])
    for zone in payload["zones"]:
        trade = trades[zone["trade_id"]]
        assert zone["bottom"] <= zone["top"]
        assert zone["start_idx"] <= trade["entry_idx"] <= zone["end_idx"]
        assert zone["type"] in ("RBS", "SBR", "SWEEP")
        # The shaded band is the level the strategy retested, so it must sit on
        # the correct side of the entry and stay inside the stop distance.
        if zone["type"] == "RBS":
            assert zone["bottom"] - 3.0 <= trade["entry_price"]
        elif zone["type"] == "SBR":
            assert trade["entry_price"] <= zone["top"] + 3.0


def test_dual_mode_includes_sweep_reversal_trades():
    payload = replay_engine.generate_replay_session("m_2026_10", "dual_mode", 1.5)
    modes = {t["mode"] for t in payload["trades"]}
    assert modes <= {"RETEST_CONTINUATION", "SWEEP_REVERSAL"}
    assert payload["meta"]["strategy"] == "dual_mode"


# ------------------------------------------------------------------- API layer


def test_api_defaults_to_longest_m5_session():
    payload = _api(
        session_id=None,
        strategy="mode_a_pure",
        rr_ratio=1.5,
        start_date=None,
        end_date=None,
    )
    assert payload["meta"]["session_id"] == "m5_all"
    assert payload["meta"]["timeframe"] == "M5"


def test_api_rejects_unknown_strategy_and_bad_rr():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as bad_strategy:
        _api(
            session_id="m_2026_10",
            strategy="nope",
            rr_ratio=1.5,
            start_date=None,
            end_date=None,
        )
    assert bad_strategy.value.status_code == 400

    with pytest.raises(HTTPException) as bad_rr:
        _api(
            session_id="m_2026_10",
            strategy="mode_a_pure",
            rr_ratio=9.0,
            start_date=None,
            end_date=None,
        )
    assert bad_rr.value.status_code == 400


# ------------------------------------------------------------------- R:R presets


def test_catalogue_exposes_rr_presets_with_a_single_parity_pin():
    data = replay_sessions()
    presets = data["rr_presets"]
    values = [p["value"] for p in presets]

    assert data["default_rr"] == replay_engine.DEFAULT_RR
    assert data["default_rr"] in values
    # Exactly one preset may claim report parity, and it must be the default.
    parity = [p for p in presets if p["is_parity"]]
    assert len(parity) == 1
    assert parity[0]["value"] == replay_engine.DEFAULT_RR
    # Every non-parity preset must be explicitly marked as exploratory.
    assert all(p["is_parity"] is False for p in presets if p is not parity[0])


def test_rr_presets_stay_inside_the_engine_accepted_range():
    for preset in replay_engine.RR_PRESETS:
        value = float(preset["value"])
        assert 0.5 <= value <= 5.0, f"{value} outside the API's accepted range"
        assert preset["label"]


def test_rr_ratio_changes_the_trade_set_but_not_the_pinned_one():
    """Guard the parity contract: 1.5 is pinned, other R:R are exploratory."""
    pinned = replay_engine.generate_replay_session("m_2026_10", "mode_a_pure", 1.5)
    other = replay_engine.generate_replay_session("m_2026_10", "mode_a_pure", 2.0)

    assert pinned["meta"]["rr_ratio"] == 1.5
    assert other["meta"]["rr_ratio"] == 2.0
    assert pinned["meta"]["total_trades"] == 48

    # R:R moves the take-profit, not the entry logic, so the *number* of setups
    # is unchanged while every outcome (and therefore the equity curve) differs.
    # If these ever matched, the selector would be silently ignored.
    assert other["meta"]["final_capital"] != pinned["meta"]["final_capital"]
    assert other["meta"]["win_rate"] != pinned["meta"]["win_rate"]

    pinned_tp = [t["tp_price"] for t in pinned["trades"]]
    other_tp = [t["tp_price"] for t in other["trades"]]
    assert pinned_tp != other_tp

    pinned_entries = [t["entry_price"] for t in pinned["trades"]]
    other_entries = [t["entry_price"] for t in other["trades"]]
    assert pinned_entries == other_entries, "entry logic must be R:R independent"


def test_rr_ratio_is_part_of_the_cache_key():
    """Two R:R values must never collide in the in-process payload cache."""
    a = replay_engine.generate_replay_session("m_2026_10", "mode_a_pure", 1.5)
    b = replay_engine.generate_replay_session("m_2026_10", "mode_a_pure", 2.0)
    c = replay_engine.generate_replay_session("m_2026_10", "mode_a_pure", 1.5)

    assert a is c, "identical requests should be served from cache"
    assert a is not b, "different R:R must not share a cache entry"
    assert b["meta"]["rr_ratio"] == 2.0


def test_api_custom_date_range_selects_contiguous_months():
    payload = _api(
        session_id=None,
        strategy="mode_a_pure",
        rr_ratio=1.5,
        start_date="2026-09-01",
        end_date="2026-10-31",
    )
    meta = payload["meta"]
    assert meta["session_id"].startswith("custom_")
    assert meta["timeframe"] == "M5"
    months = {t["month"] for t in payload["trades"]}
    assert months <= {"2026-09", "2026-10"}


def test_api_rejects_inverted_custom_range():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _api(
            session_id=None,
            strategy="mode_a_pure",
            rr_ratio=1.5,
            start_date="2026-10-01",
            end_date="2026-09-01",
        )
    assert exc.value.status_code == 400


def test_payload_is_cached_between_calls():
    first = replay_engine.generate_replay_session("m_2026_10", "mode_a_pure", 1.5)
    second = replay_engine.generate_replay_session("m_2026_10", "mode_a_pure", 1.5)
    assert first is second


def test_scan_months_only_reports_loadable_pairs():
    for month in replay_engine.scan_months():
        assert month.bars > 0
        assert month.ltf in ("M5", "M15")
        assert month.htf in ("M15", "H1")
        assert date(month.year, month.month, 1) <= date.today()
