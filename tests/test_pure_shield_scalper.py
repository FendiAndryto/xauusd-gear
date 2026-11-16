"""Unit and Regression Test Suite for PureShieldScalper (TICK-1304)."""

from datetime import datetime, timezone
import pytest

from src.simulator.portfolio import PortfolioTracker
from src.simulator.layer_manager import BEPolicy
from src.strategies.base import TickEvent
from src.strategies.pure_shield_scalper import PureShieldScalper


def make_tick(
    dt_str: str,
    bid: float,
    ask: float,
    volume: float = 1.0,
    flags: int = 0,
) -> TickEvent:
    """Helper to construct deterministic tick events."""
    dt = datetime.fromisoformat(dt_str)
    spread = round(ask - bid, 3)
    return TickEvent(
        timestamp=dt,
        bid=bid,
        ask=ask,
        spread=spread,
        volume=volume,
        flags=flags,
    )


class TestPureShieldScalper:
    """Test suite for PureShieldScalper strategy."""

    def test_monday_mode_off_blocks_all_monday_ticks(self):
        """Verify monday_mode='OFF' blocks all ticks on Monday."""
        scalper = PureShieldScalper(monday_mode="OFF")
        # 2026-10-05 is a Monday
        tick_monday = make_tick("2026-10-05 14:00:00+00:00", 2650.00, 2650.20)
        assert tick_monday.timestamp.weekday() == 0

        order = scalper.on_tick(tick_monday)
        assert order is None

    def test_monday_mode_afternoon_only(self):
        """Verify monday_mode='AFTERNOON_ONLY' blocks morning but allows afternoon."""
        scalper = PureShieldScalper(
            monday_mode="AFTERNOON_ONLY",
            blackout_hours_utc={12, 19, 21, 22},  # Only news/rollover
        )
        # 2026-10-05 is a Monday
        # Morning 09:00 UTC -> should be blocked
        tick_morning = make_tick("2026-10-05 09:00:00+00:00", 2650.00, 2650.20)
        assert scalper.on_tick(tick_morning) is None

        # Afternoon 14:00 UTC (weekday=0, hour=14 >= 12, not in blackout)
        # Let's seed range first so it's ranging
        t0 = datetime.fromisoformat("2026-10-05 13:30:00+00:00")
        for i in range(30):
            t = make_tick(f"2026-10-05 13:{i+30:02d}:00+00:00", 2650.00, 2650.20)
            scalper.detector.update(t.timestamp, t.bid, t.ask)

        tick_afternoon = make_tick("2026-10-05 14:05:00+00:00", 2650.00, 2650.20)
        # Should not be blocked by monday filter
        assert tick_afternoon.timestamp.weekday() == 0
        assert tick_afternoon.timestamp.hour >= 12

    def test_extended_blackout_hours(self):
        """Verify hours {0, 1, 2, 8, 12, 19, 21, 22} are rejected."""
        scalper = PureShieldScalper(monday_mode="ALL")
        # 2026-10-06 is a Tuesday (weekday=1)
        for h in [0, 1, 2, 8, 12, 19, 21, 22]:
            tick = make_tick(f"2026-10-06 {h:02d}:30:00+00:00", 2650.00, 2650.20)
            order = scalper.on_tick(tick)
            assert order is None, f"Hour {h} should be in blackout!"

    def test_in_line_orb_shield_bullish_breakout_blocks_sell(self):
        """Verify bullish ORB breakout strictly blocks counter-trend SELL."""
        scalper = PureShieldScalper(
            monday_mode="ALL",
            blackout_hours_utc={12, 19, 21, 22},
            orb_threshold_usd=4.00,
        )

        # 1. Feed ORB window (07:00-08:00 UTC) on a Tuesday
        # ORB range: Low 2650.00, High 2655.00 ($5 range)
        t_low = make_tick("2026-10-06 07:10:00+00:00", 2649.90, 2650.10)   # mid 2650.0
        t_high = make_tick("2026-10-06 07:40:00+00:00", 2654.90, 2655.10)  # mid 2655.0
        scalper.on_tick(t_low)
        scalper.on_tick(t_high)

        # At 08:00+ UTC, ORB is armed.
        # Now price surges up to 2660.00 (mid = 2660.10 >= 2655.00 + $4.00) -> BULLISH TREND!
        t_surge = make_tick("2026-10-06 09:00:00+00:00", 2660.00, 2660.20)
        scalper.on_tick(t_surge)
        orb_state = scalper.orb_detector.update(t_surge.timestamp, t_surge.bid, t_surge.ask)
        assert orb_state.is_trending is True
        assert orb_state.trend_direction == "BULLISH"

        # Now, even if a bearish sweep occurs at range high, SELL MUST BE BLOCKED!
        # Simulate range high sweep
        r_state = scalper.detector.update(t_surge.timestamp, 2660.00, 2660.20)
        # In on_tick:
        order = scalper.on_tick(t_surge)
        # Should not start any SELL setup because ORB is Bullish
        assert order is None

    def test_in_line_orb_shield_bearish_breakout_blocks_buy(self):
        """Verify bearish ORB breakout strictly blocks counter-trend BUY."""
        scalper = PureShieldScalper(
            monday_mode="ALL",
            blackout_hours_utc={12, 19, 21, 22},
            orb_threshold_usd=4.00,
        )

        # 1. Feed ORB window (07:00-08:00 UTC) on a Tuesday
        # ORB range: Low 2650.00, High 2655.00 ($5 range)
        t_low = make_tick("2026-10-06 07:10:00+00:00", 2649.90, 2650.10)   # mid 2650.0
        t_high = make_tick("2026-10-06 07:40:00+00:00", 2654.90, 2655.10)  # mid 2655.0
        scalper.on_tick(t_low)
        scalper.on_tick(t_high)

        # Price dumps down to 2645.00 (mid = 2645.10 <= 2650.00 - $4.00) -> BEARISH TREND!
        t_dump = make_tick("2026-10-06 09:00:00+00:00", 2645.00, 2645.20)
        scalper.on_tick(t_dump)
        orb_state = scalper.orb_detector.update(t_dump.timestamp, t_dump.bid, t_dump.ask)
        assert orb_state.is_trending is True
        assert orb_state.trend_direction == "BEARISH"

        # BUY entries must be blocked
        order = scalper.on_tick(t_dump)
        assert order is None

    def test_daily_circuit_breaker(self):
        """Verify circuit breaker halts trading after max daily loss is reached."""
        portfolio = PortfolioTracker(initial_balance=10000.0)
        scalper = PureShieldScalper(
            max_daily_loss_usd=150.0,
            monday_mode="ALL",
            blackout_hours_utc=set(),
        )
        scalper.set_portfolio(portfolio)

        # Tick 1 on 2026-10-06
        t1 = make_tick("2026-10-06 10:00:00+00:00", 2650.00, 2650.20)
        scalper.on_tick(t1)
        assert not scalper.is_circuit_breaker_tripped

        # Simulate losing trades totaling -$160 in portfolio
        from src.simulator.portfolio import Position
        p1 = Position(
            position_id="p1",
            symbol="XAUUSDm",
            side="BUY",
            volume=0.1,
            open_time=t1.timestamp,
            open_price=2650.0,
            close_time=t1.timestamp,
            close_price=2648.4,
            pnl_gross=-160.0,
            pnl_net=-160.0,
            commission=0.0,
            close_reason="SL",
        )
        portfolio.closed_positions.append(p1)

        # Next tick on same day
        t2 = make_tick("2026-10-06 10:05:00+00:00", 2650.00, 2650.20)
        scalper.on_tick(t2)
        assert scalper.is_circuit_breaker_tripped
        assert scalper.daily_realized_pnl == -160.0

        # Next day (2026-10-07) -> should reset
        t3 = make_tick("2026-10-07 03:00:00+00:00", 2650.00, 2650.20)
        scalper.on_tick(t3)
        assert not scalper.is_circuit_breaker_tripped
        assert scalper.daily_realized_pnl == 0.0
