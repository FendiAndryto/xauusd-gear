"""Unit tests for RangeSweepScalperV6 (TICK-704 / EXP-08)."""

from datetime import datetime, timezone
import pytest

from src.strategies.range_sweep_scalper_v6 import RangeSweepScalperV6
from src.strategies.base import TickEvent


def test_v6_normal_dual_direction_lifecycle():
    scalper = RangeSweepScalperV6(
        lookback_minutes=10,
        min_range_usd=3.0,
        max_range_usd=10.0,
        min_sweep_usd=0.75,
        max_sweep_usd=2.00,
        hard_sl_offset_usd=1.20,
    )

    t0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)  # London Midday (Active hour)

    # Establish range between 2650.00 and 2656.00 (width = $6.00)
    for m in range(7):
        for s in range(0, 60, 15):
            t = t0.replace(minute=m, second=s)
            p = 2650.00 if s % 30 == 0 else 2656.00
            scalper.on_tick(TickEvent(t, bid=p, ask=p + 0.24, spread=0.24, volume=1.0, flags=6))

    # Sweep below Range Low
    t_sweep = t0.replace(minute=7, second=5)
    scalper.on_tick(TickEvent(t_sweep, bid=2649.10, ask=2649.34, spread=0.24, volume=1.0, flags=6))

    # Reject back up into range -> BUY signal!
    t_reject = t0.replace(minute=7, second=10)
    sig = scalper.on_tick(TickEvent(t_reject, bid=2650.30, ask=2650.54, spread=0.24, volume=1.0, flags=6))

    assert sig is not None
    assert sig.order_type == "OPEN"
    assert sig.side == "BUY"
    assert sig.volume == 0.05
    assert scalper.layer_mgr.has_active_setup is True


def test_v6_macro_bullish_blocks_sell_and_allows_buy():
    """Verify that during a STRONG_BULLISH macro trend, SELL is blocked but BUY is allowed."""
    scalper = RangeSweepScalperV6(
        lookback_minutes=10,
        min_range_usd=3.0,
        max_range_usd=10.0,
        macro_threshold_usd=2.00,
    )

    # 1. Feed 10 hours of rising prices to train MacroTrendDetector into STRONG_BULLISH
    base = 2600.00
    for hr in range(10):
        t_hr = datetime(2026, 8, 1, hr, 15, 0, tzinfo=timezone.utc)
        p = base + hr * 6.00
        scalper.macro_detector.update(t_hr, bid=p, ask=p + 0.24)

    # Check macro state
    macro_state = scalper.macro_detector.update(datetime(2026, 8, 1, 10, 1, 0, tzinfo=timezone.utc), bid=2665.00, ask=2665.24)
    assert macro_state.regime == "STRONG_BULLISH"
    assert macro_state.allow_buy is True
    assert macro_state.allow_sell is False

    # 2. Establish consolidation range between 2660.00 and 2666.00 at hour 10
    t0 = datetime(2026, 8, 1, 10, 10, 0, tzinfo=timezone.utc)
    for m in range(7):
        for s in range(0, 60, 15):
            t = t0.replace(minute=m + 10, second=s)
            p = 2660.00 if s % 30 == 0 else 2666.00
            scalper.on_tick(TickEvent(t, bid=p, ask=p + 0.24, spread=0.24, volume=1.0, flags=6))

    # 3. Test SELL Setup (Sweep Range High 2666.00 + 0.90 = 2666.90, then re-enter)
    t_sweep_high = t0.replace(minute=17, second=5)
    scalper.on_tick(TickEvent(t_sweep_high, bid=2666.90, ask=2667.14, spread=0.24, volume=1.0, flags=6))

    t_reject_high = t0.replace(minute=17, second=10)
    sig_sell = scalper.on_tick(TickEvent(t_reject_high, bid=2665.80, ask=2666.04, spread=0.24, volume=1.0, flags=6))

    # MUST BE BLOCKED BY SHIELD!
    assert sig_sell is None
    assert scalper.layer_mgr.has_active_setup is False

    # 4. Test BUY Setup (Sweep Range Low 2660.00 - 0.90 = 2659.10, then re-enter)
    t_sweep_low = t0.replace(minute=18, second=5)
    scalper.on_tick(TickEvent(t_sweep_low, bid=2659.00, ask=2659.24, spread=0.24, volume=1.0, flags=6))

    t_reject_low = t0.replace(minute=18, second=10)
    sig_buy = scalper.on_tick(TickEvent(t_reject_low, bid=2660.20, ask=2660.44, spread=0.24, volume=1.0, flags=6))

    # MUST BE ALLOWED BY SHIELD!
    assert sig_buy is not None
    assert sig_buy.side == "BUY"
    assert sig_buy.volume == 0.05


def test_v6_macro_bearish_blocks_buy_and_allows_sell():
    """Verify that during a STRONG_BEARISH macro trend, BUY is blocked but SELL is allowed."""
    scalper = RangeSweepScalperV6(
        lookback_minutes=10,
        min_range_usd=3.0,
        max_range_usd=10.0,
        macro_threshold_usd=2.00,
    )

    # 1. Feed 10 hours of falling prices to train MacroTrendDetector into STRONG_BEARISH
    base = 2700.00
    for hr in range(10):
        t_hr = datetime(2026, 7, 1, hr, 15, 0, tzinfo=timezone.utc)
        p = base - hr * 6.00
        scalper.macro_detector.update(t_hr, bid=p, ask=p + 0.24)

    # Check macro state
    macro_state = scalper.macro_detector.update(datetime(2026, 7, 1, 10, 1, 0, tzinfo=timezone.utc), bid=2635.00, ask=2635.24)
    assert macro_state.regime == "STRONG_BEARISH"
    assert macro_state.allow_buy is False
    assert macro_state.allow_sell is True

    # 2. Establish consolidation range between 2630.00 and 2636.00 at hour 10
    t0 = datetime(2026, 7, 1, 10, 10, 0, tzinfo=timezone.utc)
    for m in range(7):
        for s in range(0, 60, 15):
            t = t0.replace(minute=m + 10, second=s)
            p = 2630.00 if s % 30 == 0 else 2636.00
            scalper.on_tick(TickEvent(t, bid=p, ask=p + 0.24, spread=0.24, volume=1.0, flags=6))

    # 3. Test BUY Setup (Sweep Range Low 2630.00 - 0.90 = 2629.10, then re-enter)
    t_sweep_low = t0.replace(minute=17, second=5)
    scalper.on_tick(TickEvent(t_sweep_low, bid=2629.00, ask=2629.24, spread=0.24, volume=1.0, flags=6))

    t_reject_low = t0.replace(minute=17, second=10)
    sig_buy = scalper.on_tick(TickEvent(t_reject_low, bid=2630.20, ask=2630.44, spread=0.24, volume=1.0, flags=6))

    # MUST BE BLOCKED BY SHIELD!
    assert sig_buy is None
    assert scalper.layer_mgr.has_active_setup is False

    # 4. Test SELL Setup (Sweep Range High 2636.00 + 0.90 = 2636.90, then re-enter)
    t_sweep_high = t0.replace(minute=18, second=5)
    scalper.on_tick(TickEvent(t_sweep_high, bid=2636.90, ask=2637.14, spread=0.24, volume=1.0, flags=6))

    t_reject_high = t0.replace(minute=18, second=10)
    sig_sell = scalper.on_tick(TickEvent(t_reject_high, bid=2635.80, ask=2636.04, spread=0.24, volume=1.0, flags=6))

    # MUST BE ALLOWED BY SHIELD!
    assert sig_sell is not None
    assert sig_sell.side == "SELL"
    assert sig_sell.volume == 0.05
