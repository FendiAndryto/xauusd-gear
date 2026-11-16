"""Unit tests for MacroTrendDetector (TICK-702 / EXP-08)."""

from datetime import datetime, timezone
import pytest

from src.strategies.macro_trend_detector import MacroTrendDetector


def test_macro_detector_initial_state():
    detector = MacroTrendDetector(fast_hours=8, slow_hours=24, trend_threshold_usd=2.50)
    t0 = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    
    # First tick
    state = detector.update(t0, bid=2650.00, ask=2650.24)
    assert state.regime == "BALANCED_SIDEWAY"
    assert state.allow_buy is True
    assert state.allow_sell is True
    assert state.completed_bars_count == 0


def test_macro_detector_bullish_regime():
    """Simulate strong rally across 10 hours and verify STRONG_BULLISH regime."""
    detector = MacroTrendDetector(fast_hours=8, slow_hours=24, trend_threshold_usd=2.50)
    t0 = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    
    # 10 hours with price rising +$5.00 each hour
    base_price = 2650.00
    for hr in range(10):
        t_hour = datetime(2026, 8, 1, hr, 30, tzinfo=timezone.utc)
        p = base_price + hr * 5.00
        state = detector.update(t_hour, bid=p, ask=p + 0.24)

    # Next hour tick to turn over bar 9
    t_end = datetime(2026, 8, 1, 10, 5, tzinfo=timezone.utc)
    state = detector.update(t_end, bid=base_price + 55.00, ask=base_price + 55.24)

    assert state.completed_bars_count >= 5
    assert state.fast_ema > state.slow_ema
    assert state.trend_spread >= 2.50
    assert state.regime == "STRONG_BULLISH"
    assert state.allow_buy is True
    assert state.allow_sell is False  # Counter-trend sell blocked!


def test_macro_detector_bearish_regime():
    """Simulate strong selloff across 10 hours and verify STRONG_BEARISH regime."""
    detector = MacroTrendDetector(fast_hours=8, slow_hours=24, trend_threshold_usd=2.50)
    base_price = 2700.00
    for hr in range(10):
        t_hour = datetime(2026, 7, 1, hr, 30, tzinfo=timezone.utc)
        p = base_price - hr * 5.00
        state = detector.update(t_hour, bid=p, ask=p + 0.24)

    t_end = datetime(2026, 7, 1, 10, 5, tzinfo=timezone.utc)
    state = detector.update(t_end, bid=base_price - 55.00, ask=base_price - 55.24)

    assert state.completed_bars_count >= 5
    assert state.fast_ema < state.slow_ema
    assert state.trend_spread <= -2.50
    assert state.regime == "STRONG_BEARISH"
    assert state.allow_buy is False  # Counter-trend buy blocked!
    assert state.allow_sell is True


def test_macro_detector_sideway_balanced():
    """Simulate sideways range across 15 hours and verify BALANCED_SIDEWAY."""
    detector = MacroTrendDetector(fast_hours=8, slow_hours=24, trend_threshold_usd=2.50)
    base_price = 2650.00
    for hr in range(15):
        t_hour = datetime(2026, 11, 1, hr, 30, tzinfo=timezone.utc)
        p = base_price + (1.0 if hr % 2 == 0 else -1.0)
        state = detector.update(t_hour, bid=p, ask=p + 0.24)

    t_end = datetime(2026, 11, 1, 15, 5, tzinfo=timezone.utc)
    state = detector.update(t_end, bid=base_price, ask=base_price + 0.24)

    assert abs(state.trend_spread) < 2.50
    assert state.regime == "BALANCED_SIDEWAY"
    assert state.allow_buy is True
    assert state.allow_sell is True
