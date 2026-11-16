"""Unit tests for RangeSweepScalperV7 (TICK-804 / EXP-09)."""

from datetime import datetime, timezone
import pytest

from src.strategies.range_sweep_scalper_v7 import RangeSweepScalperV7
from src.strategies.base import TickEvent


def test_v7_hybrid_quant_lifecycle():
    scalper = RangeSweepScalperV7(
        lookback_minutes=20,
        min_range_usd=4.0,
        max_range_usd=15.0,
        min_sweep_usd=0.80,
        max_sweep_usd=2.50,
        hard_sl_offset_usd=1.40,
    )

    t0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)  # London Midday (Active hour)

    # Establish range between 2650.00 and 2658.00 (width = $8.00)
    for m in range(12):
        for s in range(0, 60, 15):
            t = t0.replace(minute=m, second=s)
            p = 2650.00 if s % 30 == 0 else 2658.00
            scalper.on_tick(TickEvent(t, bid=p, ask=p + 0.24, spread=0.24, volume=1.0, flags=6))

    # Sweep below Range Low (2650 - 0.95 = 2649.05)
    t_sweep = t0.replace(minute=12, second=5)
    scalper.on_tick(TickEvent(t_sweep, bid=2649.00, ask=2649.24, spread=0.24, volume=1.0, flags=6))

    # Reject back up into range -> BUY signal!
    t_reject = t0.replace(minute=12, second=10)
    sig = scalper.on_tick(TickEvent(t_reject, bid=2650.30, ask=2650.54, spread=0.24, volume=1.0, flags=6))

    assert sig is not None
    assert sig.order_type == "OPEN"
    assert sig.side == "BUY"
    assert sig.volume == 0.05
    assert scalper.layer_mgr.has_active_setup is True


def test_v7_macro_bullish_shield_blocks_sell_and_allows_buy():
    scalper = RangeSweepScalperV7(
        lookback_minutes=20,
        min_range_usd=4.0,
        max_range_usd=15.0,
        macro_threshold_usd=2.00,
    )

    # 1. Feed 10 hours of rising prices to train MacroTrendDetector into STRONG_BULLISH
    base = 2600.00
    for hr in range(10):
        t_hr = datetime(2026, 8, 1, hr, 15, 0, tzinfo=timezone.utc)
        p = base + hr * 6.00
        scalper.macro_detector.update(t_hr, bid=p, ask=p + 0.24)

    macro_state = scalper.macro_detector.update(datetime(2026, 8, 1, 10, 1, 0, tzinfo=timezone.utc), bid=2665.00, ask=2665.24)
    assert macro_state.regime == "STRONG_BULLISH"
    assert macro_state.allow_buy is True
    assert macro_state.allow_sell is False

    # 2. Establish consolidation range between 2660.00 and 2668.00 (width = $8.00)
    t0 = datetime(2026, 8, 1, 10, 10, 0, tzinfo=timezone.utc)
    for m in range(12):
        for s in range(0, 60, 15):
            t = t0.replace(minute=m + 10, second=s)
            p = 2660.00 if s % 30 == 0 else 2668.00
            scalper.on_tick(TickEvent(t, bid=p, ask=p + 0.24, spread=0.24, volume=1.0, flags=6))

    # 3. Test SELL Setup (Sweep Range High 2668.00 + 0.90 = 2668.90, then re-enter)
    t_sweep_high = t0.replace(minute=23, second=5)
    scalper.on_tick(TickEvent(t_sweep_high, bid=2668.90, ask=2669.14, spread=0.24, volume=1.0, flags=6))

    t_reject_high = t0.replace(minute=23, second=10)
    sig_sell = scalper.on_tick(TickEvent(t_reject_high, bid=2667.80, ask=2668.04, spread=0.24, volume=1.0, flags=6))

    # MUST BE BLOCKED BY SHIELD!
    assert sig_sell is None
    assert scalper.layer_mgr.has_active_setup is False

    # 4. Test BUY Setup (Sweep Range Low 2660.00 - 0.90 = 2659.10, then re-enter)
    t_sweep_low = t0.replace(minute=24, second=5)
    scalper.on_tick(TickEvent(t_sweep_low, bid=2659.00, ask=2659.24, spread=0.24, volume=1.0, flags=6))

    t_reject_low = t0.replace(minute=24, second=10)
    sig_buy = scalper.on_tick(TickEvent(t_reject_low, bid=2660.20, ask=2660.44, spread=0.24, volume=1.0, flags=6))

    # MUST BE ALLOWED BY SHIELD!
    assert sig_buy is not None
    assert sig_buy.side == "BUY"
    assert sig_buy.volume == 0.05


def test_v7_minimum_range_4_usd_gate():
    """Verify ranges narrower than $4.00 are rejected as chop."""
    scalper = RangeSweepScalperV7(
        lookback_minutes=15,
        min_range_usd=4.0,
        max_range_usd=15.0,
    )

    t0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
    # Range is only $2.00 (2650.00 to 2652.00)
    for m in range(10):
        for s in range(0, 60, 15):
            t = t0.replace(minute=m, second=s)
            p = 2650.00 if s % 30 == 0 else 2652.00
            scalper.on_tick(TickEvent(t, bid=p, ask=p + 0.24, spread=0.24, volume=1.0, flags=6))

    t_sweep = t0.replace(minute=10, second=5)
    scalper.on_tick(TickEvent(t_sweep, bid=2649.00, ask=2649.24, spread=0.24, volume=1.0, flags=6))

    t_reject = t0.replace(minute=10, second=10)
    sig = scalper.on_tick(TickEvent(t_reject, bid=2650.50, ask=2650.74, spread=0.24, volume=1.0, flags=6))

    # Blocked because range width ($2.00) < min_range_usd ($4.00)
    assert sig is None
