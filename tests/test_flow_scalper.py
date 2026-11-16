"""Unit tests for FlowMomentumScalper strategy."""

from datetime import datetime, timezone
import pytest

from src.simulator.portfolio import PortfolioTracker
from src.strategies.base import TickEvent
from src.strategies.flow_momentum_scalper import FlowMomentumScalper


def test_hour_and_spread_filters():
    strat = FlowMomentumScalper(
        window_ticks=3,
        momentum_threshold_usd=0.30,
        max_spread_usd=0.25,
        allowed_hours_utc={14},  # only 14:00 UTC allowed
    )

    # Tick at 10:00 UTC (not allowed hour)
    t_bad_hour = TickEvent(datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc), 2650.0, 2650.24, 0.24, 1.0, 6)
    assert strat.on_tick(t_bad_hour) is None

    # Tick at 14:00 UTC but wide spread ($0.35 > $0.25)
    t_wide_spread = TickEvent(datetime(2026, 10, 1, 14, 0, 0, tzinfo=timezone.utc), 2650.0, 2650.35, 0.35, 1.0, 6)
    assert strat.on_tick(t_wide_spread) is None


def test_velocity_burst_signal():
    strat = FlowMomentumScalper(
        window_ticks=3,
        momentum_threshold_usd=0.30,
        max_elapsed_seconds=2.0,
        max_spread_usd=0.25,
        allowed_hours_utc={14},
    )

    # 3 ticks arriving within 1.0 second with price surge of $0.40
    t1 = TickEvent(datetime(2026, 10, 1, 14, 0, 0, 0, tzinfo=timezone.utc), 2650.00, 2650.24, 0.24, 1.0, 6)
    t2 = TickEvent(datetime(2026, 10, 1, 14, 0, 0, 500_000, tzinfo=timezone.utc), 2650.20, 2650.44, 0.24, 1.0, 6)
    t3 = TickEvent(datetime(2026, 10, 1, 14, 0, 1, 0, tzinfo=timezone.utc), 2650.40, 2650.64, 0.24, 1.0, 6)

    assert strat.on_tick(t1) is None
    assert strat.on_tick(t2) is None
    sig = strat.on_tick(t3)

    assert sig is not None
    assert sig.order_type == "OPEN"
    assert sig.side == "BUY"
    assert sig.reason == "FLOW_BUY_BURST"


def test_time_stop_trigger():
    portfolio = PortfolioTracker()
    strat = FlowMomentumScalper(max_hold_seconds=60.0)
    strat.set_portfolio(portfolio)

    t0 = datetime(2026, 10, 1, 14, 0, 0, tzinfo=timezone.utc)
    portfolio.open_position("BUY", volume=0.5, price=2650.24, timestamp=t0)

    # 70 seconds later (exceeds max_hold_seconds of 60s)
    t_later = TickEvent(datetime(2026, 10, 1, 14, 1, 10, tzinfo=timezone.utc), 2650.30, 2650.54, 0.24, 1.0, 6)
    sig = strat.on_tick(t_later)

    assert sig is not None
    assert sig.order_type == "CLOSE"
    assert sig.reason == "TIME_STOP"
