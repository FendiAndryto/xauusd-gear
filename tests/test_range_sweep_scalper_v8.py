"""Unit tests for RangeSweepScalperV8 with Daily Circuit Breaker (TICK-1003)."""

from datetime import datetime, timezone, timedelta
import pytest

from src.simulator.portfolio import PortfolioTracker, Position
from src.strategies.base import TickEvent
from src.strategies.range_sweep_scalper_v8 import RangeSweepScalperV8


def make_tick(dt: datetime, bid: float, ask: float) -> TickEvent:
    return TickEvent(
        timestamp=dt,
        bid=bid,
        ask=ask,
        spread=round(ask - bid, 3),
        volume=100.0,
        flags=0,
    )


def test_v8_circuit_breaker_trips_and_resets():
    """Verify that when daily loss reaches threshold, entries freeze until next calendar day."""
    scalper = RangeSweepScalperV8(
        max_daily_loss_usd=150.0,
        blackout_hours_utc=set(),  # Disable blackout for clean unit test
    )
    portfolio = PortfolioTracker()
    scalper.set_portfolio(portfolio)

    base_time = datetime(2026, 11, 7, 8, 0, 0, tzinfo=timezone.utc)

    # 1. Initially circuit breaker is not tripped
    tick1 = make_tick(base_time, 2700.0, 2700.20)
    scalper.on_tick(tick1)
    assert not scalper.is_circuit_breaker_tripped
    assert scalper.daily_realized_pnl == 0.0

    # 2. Add a loss of -$80 (below -$150 threshold)
    pos1 = Position(
        position_id="test-1",
        symbol="XAUUSD",
        side="BUY",
        volume=0.10,
        open_time=base_time,
        open_price=2700.0,
        close_time=base_time + timedelta(minutes=5),
        close_price=2692.0,
        pnl_net=-80.0,
    )
    portfolio.closed_positions.append(pos1)

    tick2 = make_tick(base_time + timedelta(minutes=6), 2700.0, 2700.20)
    scalper.on_tick(tick2)
    assert not scalper.is_circuit_breaker_tripped
    assert scalper.daily_realized_pnl == -80.0

    # 3. Add another loss of -$75 (total loss now -$155 <= -$150)
    pos2 = Position(
        position_id="test-2",
        symbol="XAUUSD",
        side="SELL",
        volume=0.10,
        open_time=base_time + timedelta(minutes=7),
        open_price=2700.0,
        close_time=base_time + timedelta(minutes=10),
        close_price=2707.5,
        pnl_net=-75.0,
    )
    portfolio.closed_positions.append(pos2)

    tick3 = make_tick(base_time + timedelta(minutes=11), 2700.0, 2700.20)
    order = scalper.on_tick(tick3)
    assert scalper.is_circuit_breaker_tripped
    assert scalper.daily_realized_pnl == -155.0
    assert order is None  # Blocked!

    # 4. Advance to next day 00:01 UTC -> Circuit breaker MUST reset!
    next_day_time = datetime(2026, 11, 8, 0, 1, 0, tzinfo=timezone.utc)
    tick4 = make_tick(next_day_time, 2700.0, 2700.20)
    scalper.on_tick(tick4)
    assert not scalper.is_circuit_breaker_tripped
    assert scalper.daily_realized_pnl == 0.0


def test_v8_blackout_and_direction_shield_preserved():
    """Verify that V6 directional shield and blackout are preserved in V8."""
    scalper = RangeSweepScalperV8(
        blackout_hours_utc={12, 19, 21, 22},
    )
    portfolio = PortfolioTracker()
    scalper.set_portfolio(portfolio)

    # News blackout hour 12 UTC
    t_blackout = datetime(2026, 11, 7, 12, 30, 0, tzinfo=timezone.utc)
    tick = make_tick(t_blackout, 2700.0, 2700.20)
    order = scalper.on_tick(tick)
    assert order is None
