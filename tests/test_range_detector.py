"""Unit tests for RangeDetector (TICK-301)."""

from datetime import datetime, timedelta, timezone
import pytest

from src.strategies.range_detector import RangeDetector


def test_range_detector_ranging_state():
    detector = RangeDetector(
        lookback_minutes=10,
        min_range_usd=3.0,
        max_range_usd=10.0,
    )

    t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Feed 7 minutes of completed bars oscillating between 2650.00 and 2655.00
    for m in range(7):
        for s in range(0, 60, 10):
            t = t0 + timedelta(minutes=m, seconds=s)
            price = 2650.00 if s % 20 == 0 else 2655.00
            state = detector.update(t, bid=price, ask=price + 0.24)

    # In minute 7, we should have 6 completed bars
    t_check = t0 + timedelta(minutes=7, seconds=5)
    state = detector.update(t_check, bid=2652.0, ask=2652.24)

    assert state.is_ranging is True
    assert state.range_high == 2655.12
    assert state.range_low == 2650.12
    assert abs(state.range_width - 5.0) < 0.01
    assert abs(state.equilibrium - 2652.62) < 0.01
    assert state.circuit_breaker_active is False


def test_range_detector_rejects_narrow_range():
    detector = RangeDetector(lookback_minutes=10, min_range_usd=3.0, max_range_usd=10.0)
    t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Range of only $1.00 (too narrow)
    for m in range(7):
        for s in range(0, 60, 10):
            t = t0 + timedelta(minutes=m, seconds=s)
            price = 2650.00 if s % 20 == 0 else 2651.00
            state = detector.update(t, bid=price, ask=price + 0.24)

    t_check = t0 + timedelta(minutes=7, seconds=5)
    state = detector.update(t_check, bid=2650.5, ask=2650.74)
    assert state.is_ranging is False
    assert state.range_width < 3.0


def test_range_detector_circuit_breaker():
    detector = RangeDetector(max_tick_velocity=10.0)
    t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Feed 15 ticks within 0.5 second (30 ticks/sec -> news surge!)
    for i in range(15):
        t = t0 + timedelta(milliseconds=i * 30)
        state = detector.update(t, bid=2650.0, ask=2650.24)

    assert state.circuit_breaker_active is True
    assert state.is_ranging is False
