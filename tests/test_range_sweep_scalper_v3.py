"""Unit tests for RangeSweepScalperV3 (TICK-404)."""

from datetime import datetime, timezone
import pytest

from src.strategies.range_sweep_scalper_v3 import RangeSweepScalperV3
from src.strategies.base import TickEvent


def test_v3_session_aware_buy_setup():
    scalper = RangeSweepScalperV3(
        lookback_minutes=10,
        min_range_usd=5.0,
        max_range_usd=12.0,
        min_sweep_usd=0.70,
        max_sweep_usd=2.00,
        hard_sl_offset_usd=1.00,
        be_policy="BUFFER",
    )

    t0 = datetime(2026, 10, 1, 14, 0, 0, tzinfo=timezone.utc)

    # Establish range between 2650.00 and 2656.00 (width = $6.00, sweet spot)
    for m in range(7):
        for s in range(0, 60, 15):
            t = t0.replace(minute=m, second=s)
            p = 2650.00 if s % 30 == 0 else 2656.00
            scalper.on_tick(TickEvent(t, bid=p, ask=p + 0.24, spread=0.24, volume=1.0, flags=6))

    # Minute 7: Sweep below Range Low (2650.12 - 0.90 = 2649.22)
    t_sweep = t0.replace(minute=7, second=5)
    scalper.on_tick(TickEvent(t_sweep, bid=2649.10, ask=2649.34, spread=0.24, volume=1.0, flags=6))

    # Reject back up into range (bid = 2650.30 >= RL 2650.12) -> BUY signal!
    t_reject = t0.replace(minute=7, second=10)
    sig = scalper.on_tick(TickEvent(t_reject, bid=2650.30, ask=2650.54, spread=0.24, volume=1.0, flags=6))

    assert sig is not None
    assert sig.order_type == "OPEN"
    assert sig.side == "BUY"
    assert sig.volume == 0.05  # Prime session (14:00 UTC) = 100% volume
    assert sig.sl < 2649.30     # Hard SL set below trough
