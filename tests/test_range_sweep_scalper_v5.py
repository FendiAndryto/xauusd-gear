"""Unit tests for RangeSweepScalperV5 (TICK-603 / EXP-06)."""

from datetime import datetime, timezone
import pytest

from src.simulator.portfolio import PortfolioTracker
from src.strategies.range_sweep_scalper_v5 import RangeSweepScalperV5
from src.strategies.base import TickEvent


def test_v5_step_lock_lifecycle():
    scalper = RangeSweepScalperV5(
        lookback_minutes=10,
        min_range_usd=3.0,
        max_range_usd=10.0,
        min_sweep_usd=0.75,
        max_sweep_usd=2.00,
        hard_sl_offset_usd=1.20,
        be_policy="STEP_LOCK",
    )

    t0 = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)  # London Midday (Active hour)

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


def test_v5_news_release_blackout_rejection():
    """Verify Hour 12 UTC (US Macro News) strictly blocks new order generation."""
    scalper = RangeSweepScalperV5(
        lookback_minutes=10,
        min_range_usd=3.0,
        max_range_usd=10.0,
        min_sweep_usd=0.75,
        max_sweep_usd=2.00,
    )

    t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)  # 12:00 UTC news window
    for m in range(7):
        for s in range(0, 60, 15):
            t = t0.replace(minute=m, second=s)
            p = 2650.00 if s % 30 == 0 else 2656.00
            scalper.on_tick(TickEvent(t, bid=p, ask=p + 0.24, spread=0.24, volume=1.0, flags=6))

    t_sweep = t0.replace(minute=7, second=5)
    scalper.on_tick(TickEvent(t_sweep, bid=2649.10, ask=2649.34, spread=0.24, volume=1.0, flags=6))

    t_reject = t0.replace(minute=7, second=10)
    sig = scalper.on_tick(TickEvent(t_reject, bid=2650.30, ask=2650.54, spread=0.24, volume=1.0, flags=6))

    assert sig is None
    assert scalper.layer_mgr.has_active_setup is False


def test_v5_afternoon_churn_blackout_rejection():
    """Verify Hour 19 UTC (US Afternoon Churn) strictly blocks new order generation."""
    scalper = RangeSweepScalperV5(
        lookback_minutes=10,
        min_range_usd=3.0,
        max_range_usd=10.0,
        min_sweep_usd=0.75,
        max_sweep_usd=2.00,
    )

    t0 = datetime(2026, 10, 1, 19, 0, 0, tzinfo=timezone.utc)  # 19:00 UTC churn window
    for m in range(7):
        for s in range(0, 60, 15):
            t = t0.replace(minute=m, second=s)
            p = 2650.00 if s % 30 == 0 else 2656.00
            scalper.on_tick(TickEvent(t, bid=p, ask=p + 0.24, spread=0.24, volume=1.0, flags=6))

    t_sweep = t0.replace(minute=7, second=5)
    scalper.on_tick(TickEvent(t_sweep, bid=2649.10, ask=2649.34, spread=0.24, volume=1.0, flags=6))

    t_reject = t0.replace(minute=7, second=10)
    sig = scalper.on_tick(TickEvent(t_reject, bid=2650.30, ask=2650.54, spread=0.24, volume=1.0, flags=6))

    assert sig is None
    assert scalper.layer_mgr.has_active_setup is False


def test_v5_rollover_blackout_rejection():
    """Verify Hours 21 & 22 UTC (Exness Rollover Spread Spikes) block new order generation."""
    scalper = RangeSweepScalperV5(
        lookback_minutes=10,
        min_range_usd=3.0,
        max_range_usd=10.0,
    )

    for hr in [21, 22]:
        t_rollover = datetime(2026, 10, 1, hr, 15, 0, tzinfo=timezone.utc)
        sig = scalper.on_tick(TickEvent(t_rollover, bid=2650.00, ask=2650.60, spread=0.60, volume=1.0, flags=6))
        assert sig is None


def test_v5_high_expectancy_sessions_active():
    """Verify London (07:00 UTC) and Asian (01:00 & 06:00 UTC) sessions execute at full volume."""
    for hr in [1, 6, 7]:
        scalper = RangeSweepScalperV5(
            lookback_minutes=10,
            min_range_usd=3.0,
            max_range_usd=10.0,
        )
        t0 = datetime(2026, 10, 1, hr, 0, 0, tzinfo=timezone.utc)
        for m in range(7):
            for s in range(0, 60, 15):
                t = t0.replace(minute=m, second=s)
                p = 2650.00 if s % 30 == 0 else 2656.00
                scalper.on_tick(TickEvent(t, bid=p, ask=p + 0.24, spread=0.24, volume=1.0, flags=6))

        t_sweep = t0.replace(minute=7, second=5)
        scalper.on_tick(TickEvent(t_sweep, bid=2649.10, ask=2649.34, spread=0.24, volume=1.0, flags=6))

        t_reject = t0.replace(minute=7, second=10)
        sig = scalper.on_tick(TickEvent(t_reject, bid=2650.30, ask=2650.54, spread=0.24, volume=1.0, flags=6))

        assert sig is not None, f"Hour {hr} UTC should have generated an order signal"
        assert sig.volume == 0.05


def test_v5_active_position_managed_during_blackout():
    """Verify an existing position entered before blackout is actively managed (TP/SL) during blackout."""
    portfolio = PortfolioTracker()
    scalper = RangeSweepScalperV5(
        lookback_minutes=10,
        min_range_usd=3.0,
        max_range_usd=10.0,
    )
    scalper.portfolio = portfolio

    # Enter trade at 11:58 UTC (before Hour 12 blackout)
    t0 = datetime(2026, 10, 1, 11, 50, 0, tzinfo=timezone.utc)
    for m in range(7):
        for s in range(0, 60, 15):
            t = t0.replace(minute=m + 50, second=s)
            p = 2650.00 if s % 30 == 0 else 2656.00
            scalper.on_tick(TickEvent(t, bid=p, ask=p + 0.24, spread=0.24, volume=1.0, flags=6))

    t_sweep = datetime(2026, 10, 1, 11, 57, 5, tzinfo=timezone.utc)
    scalper.on_tick(TickEvent(t_sweep, bid=2649.10, ask=2649.34, spread=0.24, volume=1.0, flags=6))

    t_reject = datetime(2026, 10, 1, 11, 58, 0, tzinfo=timezone.utc)
    sig_open = scalper.on_tick(TickEvent(t_reject, bid=2650.30, ask=2650.54, spread=0.24, volume=1.0, flags=6))
    assert sig_open is not None
    assert scalper.layer_mgr.has_active_setup is True

    # Simulate position opened in portfolio
    pos = portfolio.open_position("BUY", sig_open.volume, 2650.54, t_reject, sl=sig_open.sl, tp=sig_open.tp)
    scalper.layer_mgr.register_position(pos.position_id)

    # Now tick enters Hour 12:01 UTC (Blackout) and hits Hard SL (e.g. 2647.00 <= hard_sl)
    t_blackout_sl = datetime(2026, 10, 1, 12, 1, 0, tzinfo=timezone.utc)
    sig_close = scalper.on_tick(TickEvent(t_blackout_sl, bid=2647.00, ask=2647.24, spread=0.24, volume=1.0, flags=6))

    assert sig_close is not None
    assert sig_close.order_type == "CLOSE"
    assert sig_close.reason == "HARD_INVALIDATION_SL"
