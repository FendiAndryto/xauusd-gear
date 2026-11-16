"""Unit tests for RangeSweepScalper strategy (TICK-303)."""

from datetime import datetime, timedelta, timezone
import pytest

from src.simulator.portfolio import PortfolioTracker
from src.strategies.base import TickEvent
from src.strategies.range_sweep_scalper import RangeSweepScalper


def test_range_sweep_scalper_sell_setup():
    strat = RangeSweepScalper(
        lookback_minutes=10,
        min_range_usd=3.0,
        max_range_usd=10.0,
        min_sweep_usd=0.40,
        max_sweep_usd=1.50,
        hard_sl_offset_usd=1.00,
        max_spread_usd=0.25,
    )
    portfolio = PortfolioTracker()
    strat.set_portfolio(portfolio)

    t0 = datetime(2026, 10, 1, 14, 0, 0, tzinfo=timezone.utc)

    # 1. Establish Range: 2650.00 to 2655.00 (width = $5.00) over 6 completed minutes
    for m in range(7):
        for s in range(0, 60, 10):
            t = t0 + timedelta(minutes=m, seconds=s)
            price = 2650.00 if s % 20 == 0 else 2655.00
            strat.on_tick(TickEvent(t, bid=price, ask=price + 0.24, spread=0.24, volume=1.0, flags=6))

    # 2. In minute 7: Poke above Range High ($2655.12) to $2655.80 (penetration ~ $0.68)
    t_sweep = t0 + timedelta(minutes=7, seconds=15)
    strat.on_tick(TickEvent(t_sweep, bid=2655.70, ask=2655.94, spread=0.24, volume=1.0, flags=6))
    assert strat.high_sweep_active is True

    # 3. Reject back inside range to $2654.80 (< $2655.12) -> Triggers SELL Signal!
    t_reject = t0 + timedelta(minutes=7, seconds=20)
    sig = strat.on_tick(TickEvent(t_reject, bid=2654.70, ask=2654.94, spread=0.24, volume=1.0, flags=6))

    assert sig is not None
    assert sig.order_type == "OPEN"
    assert sig.side == "SELL"
    assert sig.volume == 0.05
    assert sig.sl > 2655.80  # Hard SL above sweep peak
    assert sig.tp < 2654.80  # TP below entry (at or near range low)
