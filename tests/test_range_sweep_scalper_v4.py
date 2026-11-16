"""Unit tests for RangeSweepScalperV4 (TICK-503)."""

from datetime import datetime, timezone
import pytest

from src.strategies.range_sweep_scalper_v4 import RangeSweepScalperV4
from src.strategies.base import TickEvent


def test_v4_step_lock_lifecycle():
    scalper = RangeSweepScalperV4(
        lookback_minutes=10,
        min_range_usd=3.0,
        max_range_usd=10.0,
        min_sweep_usd=0.75,
        max_sweep_usd=2.00,
        hard_sl_offset_usd=1.20,
        be_policy="STEP_LOCK",
    )

    t0 = datetime(2026, 10, 1, 14, 0, 0, tzinfo=timezone.utc)

    # Establish range between 2650.00 and 2656.00 (width = $6.00)
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
    assert sig.volume == 0.05
    assert scalper.layer_mgr.has_active_setup is True
    assert scalper.layer_mgr.be_policy == "STEP_LOCK"


def test_v4_rollover_blackout_rejection():
    scalper = RangeSweepScalperV4(
        lookback_minutes=10,
        min_range_usd=3.0,
        max_range_usd=10.0,
    )

    # Rollover hour (21:30 UTC)
    t_rollover = datetime(2026, 10, 1, 21, 30, 0, tzinfo=timezone.utc)
    sig = scalper.on_tick(TickEvent(t_rollover, bid=2650.00, ask=2650.60, spread=0.60, volume=1.0, flags=6))
    assert sig is None


def test_v4_asian_session_full_volume():
    scalper = RangeSweepScalperV4(
        lookback_minutes=10,
        min_range_usd=3.0,
        max_range_usd=10.0,
    )

    # Asian session hour (02:00 UTC / 09:00 WIB)
    t0 = datetime(2026, 10, 1, 2, 0, 0, tzinfo=timezone.utc)
    for m in range(7):
        for s in range(0, 60, 15):
            t = t0.replace(minute=m, second=s)
            p = 2650.00 if s % 30 == 0 else 2656.00
            scalper.on_tick(TickEvent(t, bid=p, ask=p + 0.24, spread=0.24, volume=1.0, flags=6))

    t_sweep = t0.replace(minute=7, second=5)
    scalper.on_tick(TickEvent(t_sweep, bid=2649.10, ask=2649.34, spread=0.24, volume=1.0, flags=6))

    t_reject = t0.replace(minute=7, second=10)
    sig = scalper.on_tick(TickEvent(t_reject, bid=2650.30, ask=2650.54, spread=0.24, volume=1.0, flags=6))

    assert sig is not None
    assert sig.volume == 0.05  # Full 100% volume in Asian session
