"""Unit tests for Trend State Latching and Breakout Retest Mechanics (TICK-1205).

Verifies:
1. Latch activation upon London ORB breakout.
2. Latch persistence when price pulls back into retest zone.
3. Contrast with non-latched regime detector (which prematurely resets to RANGE).
4. Latch invalidation when opposite boundary is breached.
5. Calendar day rollover reset at 00:00 UTC.
6. End-to-end VolatilityBreakoutScalperV1 entry on retest bounce under latched regime.
"""

from datetime import datetime, timezone
import pytest

from src.strategies.base import TickEvent
from src.strategies.regime_detector import MarketRegimeDetector
from src.strategies.volatility_breakout_scalper import VolatilityBreakoutScalperV1


def test_orb_trend_latch_activation_and_pullback_retention():
    """Verify that enable_trend_latch maintains trending status during pullback."""
    detector = MarketRegimeDetector(
        mode="ORB",
        orb_start_hour_utc=7,
        orb_duration_hours=1,
        orb_threshold_usd=4.00,
        enable_trend_latch=True,
    )

    # 1. Establish ORB window (07:00 - 08:00 UTC)
    t1 = datetime(2026, 8, 12, 7, 0, 0, tzinfo=timezone.utc)
    detector.update(t1, 2700.0, 2700.10)
    t2 = datetime(2026, 8, 12, 7, 30, 0, tzinfo=timezone.utc)
    detector.update(t2, 2705.0, 2705.10)  # High = 2705.05
    t3 = datetime(2026, 8, 12, 7, 59, 0, tzinfo=timezone.utc)
    detector.update(t3, 2695.0, 2695.10)  # Low = 2695.05

    # 2. Arm ORB at 08:00 UTC
    t4 = datetime(2026, 8, 12, 8, 0, 0, tzinfo=timezone.utc)
    s4 = detector.update(t4, 2702.0, 2702.10)
    assert s4.orb_active is True
    assert s4.regime == "RANGE_BOUND"
    assert s4.trend_latched is False

    # 3. Pushes into Bullish Breakout (High = 2705.05 + 4.00 = 2709.05)
    t5 = datetime(2026, 8, 12, 8, 15, 0, tzinfo=timezone.utc)
    s5 = detector.update(t5, 2709.50, 2709.60)
    assert s5.regime == "STRONG_BULLISH_TREND"
    assert s5.is_trending is True
    assert s5.trend_latched is True
    assert s5.latched_direction == "BULLISH"

    # 4. Pullback into retest zone (Price drops to 2706.00 < 2709.05 threshold)
    t6 = datetime(2026, 8, 12, 8, 25, 0, tzinfo=timezone.utc)
    s6 = detector.update(t6, 2706.00, 2706.10)
    # Under latch, it MUST REMAIN STRONG_BULLISH_TREND!
    assert s6.regime == "STRONG_BULLISH_TREND"
    assert s6.is_trending is True
    assert s6.trend_latched is True
    assert s6.latched_direction == "BULLISH"


def test_orb_without_trend_latch_resets_prematurely():
    """Verify that without latch, detector reverts to RANGE_BOUND on pullback."""
    detector = MarketRegimeDetector(
        mode="ORB",
        orb_start_hour_utc=7,
        orb_duration_hours=1,
        orb_threshold_usd=4.00,
        enable_trend_latch=False,  # Baseline EXP-12 behavior
    )

    # 1. ORB window
    t1 = datetime(2026, 8, 12, 7, 0, 0, tzinfo=timezone.utc)
    detector.update(t1, 2700.0, 2700.10)
    t2 = datetime(2026, 8, 12, 7, 30, 0, tzinfo=timezone.utc)
    detector.update(t2, 2705.0, 2705.10)
    t3 = datetime(2026, 8, 12, 7, 59, 0, tzinfo=timezone.utc)
    detector.update(t3, 2695.0, 2695.10)

    # 2. Breakout
    t4 = datetime(2026, 8, 12, 8, 15, 0, tzinfo=timezone.utc)
    s4 = detector.update(t4, 2709.50, 2709.60)
    assert s4.regime == "STRONG_BULLISH_TREND"

    # 3. Pullback to 2706.00
    t5 = datetime(2026, 8, 12, 8, 25, 0, tzinfo=timezone.utc)
    s5 = detector.update(t5, 2706.00, 2706.10)
    # Without latch, it reverts back to RANGE_BOUND!
    assert s5.regime == "RANGE_BOUND"
    assert s5.is_trending is False


def test_orb_trend_latch_invalidation():
    """Verify that if price breaks opposite boundary, latch is invalidated."""
    detector = MarketRegimeDetector(
        mode="ORB",
        orb_start_hour_utc=7,
        orb_duration_hours=1,
        orb_threshold_usd=4.00,
        enable_trend_latch=True,
    )

    t1 = datetime(2026, 8, 12, 7, 0, 0, tzinfo=timezone.utc)
    detector.update(t1, 2700.0, 2700.10)
    t2 = datetime(2026, 8, 12, 7, 30, 0, tzinfo=timezone.utc)
    detector.update(t2, 2705.0, 2705.10)  # High = 2705.05
    t3 = datetime(2026, 8, 12, 7, 59, 0, tzinfo=timezone.utc)
    detector.update(t3, 2695.0, 2695.10)  # Low = 2695.05

    # Breakout
    t4 = datetime(2026, 8, 12, 8, 15, 0, tzinfo=timezone.utc)
    s4 = detector.update(t4, 2709.50, 2709.60)
    assert s4.trend_latched is True

    # Price collapses completely below ORB Low (2695.05) to 2694.00
    t5 = datetime(2026, 8, 12, 9, 0, 0, tzinfo=timezone.utc)
    s5 = detector.update(t5, 2694.00, 2694.10)
    assert s5.regime == "RANGE_BOUND"
    assert s5.is_trending is False
    assert s5.trend_latched is False


def test_orb_trend_latch_day_rollover():
    """Verify that latch is cleanly reset on 00:00 UTC day rollover."""
    detector = MarketRegimeDetector(
        mode="ORB",
        orb_start_hour_utc=7,
        orb_duration_hours=1,
        orb_threshold_usd=4.00,
        enable_trend_latch=True,
    )

    t1 = datetime(2026, 8, 12, 7, 0, 0, tzinfo=timezone.utc)
    detector.update(t1, 2700.0, 2700.10)
    t2 = datetime(2026, 8, 12, 7, 30, 0, tzinfo=timezone.utc)
    detector.update(t2, 2705.0, 2705.10)
    t3 = datetime(2026, 8, 12, 7, 59, 0, tzinfo=timezone.utc)
    detector.update(t3, 2695.0, 2695.10)

    # Breakout at 08:15 UTC
    t4 = datetime(2026, 8, 12, 8, 15, 0, tzinfo=timezone.utc)
    s4 = detector.update(t4, 2709.50, 2709.60)
    assert s4.trend_latched is True

    # Rollover to next day: 2026-08-13 00:00 UTC
    t5 = datetime(2026, 8, 13, 0, 0, 0, tzinfo=timezone.utc)
    s5 = detector.update(t5, 2712.00, 2712.10)
    assert s5.trend_latched is False
    assert s5.latched_direction == "NONE"
    assert s5.regime == "RANGE_BOUND"


def test_volatility_breakout_scalper_retest_entry():
    """Verify VolatilityBreakoutScalperV1 successfully triggers L1 entry on retest bounce."""
    scalper = VolatilityBreakoutScalperV1(
        breakout_min_penetration_usd=2.00,
        retest_max_distance_usd=1.50,
        retest_bounce_trigger_usd=0.40,
        hard_sl_offset_usd=1.50,
    )

    detector = MarketRegimeDetector(
        mode="ORB",
        orb_start_hour_utc=7,
        orb_duration_hours=1,
        orb_threshold_usd=4.00,
        enable_trend_latch=True,
    )

    # 1. ORB Range: 2700.00 to 2705.00
    t1 = datetime(2026, 8, 12, 7, 0, 0, tzinfo=timezone.utc)
    detector.update(t1, 2700.0, 2700.10)
    t2 = datetime(2026, 8, 12, 7, 30, 0, tzinfo=timezone.utc)
    detector.update(t2, 2705.0, 2705.10)  # ORB High = 2705.05
    t3 = datetime(2026, 8, 12, 7, 59, 0, tzinfo=timezone.utc)
    detector.update(t3, 2700.0, 2700.10)  # ORB Low = 2700.05

    # 2. Breakout at 08:15 UTC to 2709.50 (penetration = 4.45 >= 4.00 threshold)
    t4 = datetime(2026, 8, 12, 8, 15, 0, tzinfo=timezone.utc)
    s4 = detector.update(t4, 2709.50, 2709.60)
    assert s4.is_trending is True

    tick_breakout = TickEvent(t4, 2709.50, 2709.60, 0.10, 1.0, 0)
    req1 = scalper.on_tick_with_regime(tick_breakout, s4, 2705.05, 2700.05)
    assert req1 is None  # No entry on initial breakout (no FOMO!)
    assert scalper.bull_breakout_active is True

    # 3. Retest Pullback to 2706.20 (dist to 2705.05 is +1.15 <= 1.50 retest_max_distance)
    t5 = datetime(2026, 8, 12, 8, 20, 0, tzinfo=timezone.utc)
    s5 = detector.update(t5, 2706.20, 2706.30)
    assert s5.is_trending is True  # Retained by trend latch!

    tick_retest = TickEvent(t5, 2706.20, 2706.30, 0.10, 1.0, 0)
    req2 = scalper.on_tick_with_regime(tick_retest, s5, 2705.05, 2700.05)
    assert req2 is None  # Waiting for bounce rejection
    assert scalper.bull_retest_active is True

    # 4. Bounce Rejection to 2706.70 (+0.45 bounce >= 0.40 trigger)
    t6 = datetime(2026, 8, 12, 8, 22, 0, tzinfo=timezone.utc)
    s6 = detector.update(t6, 2706.70, 2706.80)

    tick_bounce = TickEvent(t6, 2706.70, 2706.80, 0.10, 1.0, 0)
    req3 = scalper.on_tick_with_regime(tick_bounce, s6, 2705.05, 2700.05)

    assert req3 is not None
    assert req3.order_type == "OPEN"
    assert req3.side == "BUY"
    assert req3.volume == 0.05
    assert req3.reason == "BREAKOUT_RETEST_L1"
    # SL = retest_trough (2706.25 mid) - hard_sl_offset (1.50) = 2704.75
    assert req3.sl < 2705.05
    assert scalper.has_active_campaign is True
