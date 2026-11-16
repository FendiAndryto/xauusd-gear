"""Unit and safety tests for Adaptive Dual-Engine Scalper, Regime Detector, and Pyramiding (TICK-1105)."""

from datetime import datetime, timezone, timedelta
import pytest

from src.simulator.execution import OrderRequest
from src.simulator.portfolio import PortfolioTracker, Position
from src.strategies.adaptive_dual_engine import AdaptiveDualEngineScalper
from src.strategies.base import TickEvent
from src.strategies.regime_detector import MarketRegimeDetector, MarketRegimeState
from src.strategies.volatility_breakout_scalper import VolatilityBreakoutScalperV1


def make_tick(dt: datetime, bid: float, ask: float) -> TickEvent:
    return TickEvent(
        timestamp=dt,
        bid=bid,
        ask=ask,
        spread=round(ask - bid, 3),
        volume=100.0,
        flags=0,
    )


# -------------------------------------------------------------
# 1. Market Regime Detector Tests
# -------------------------------------------------------------

def test_regime_detector_dynamic_expansion():
    """Verify that daily displacement triggers Bullish/Bearish Trend."""
    detector = MarketRegimeDetector(
        mode="DYNAMIC_EXPANSION",
        daily_expansion_threshold_usd=15.00,
    )

    t0 = datetime(2026, 11, 7, 0, 0, 0, tzinfo=timezone.utc)

    # 1. Day open at $2700.00
    state = detector.update(t0, 2700.0, 2700.20)
    assert state.regime == "RANGE_BOUND"
    assert not state.is_trending
    assert state.day_open_price == 2700.10

    # 2. Price rises by $10 (within $15 threshold) -> Still RANGE
    t1 = t0 + timedelta(hours=2)
    state = detector.update(t1, 2710.0, 2710.20)
    assert state.regime == "RANGE_BOUND"
    assert not state.is_trending

    # 3. Price rises by +$16 (exceeds $15 threshold) -> STRONG_BULLISH_TREND!
    t2 = t0 + timedelta(hours=4)
    state = detector.update(t2, 2716.20, 2716.40)
    assert state.regime == "STRONG_BULLISH_TREND"
    assert state.is_trending
    assert state.trend_direction == "BULLISH"

    # 4. Next day 00:01 UTC -> Resets to RANGE_BOUND at new day open!
    t_next_day = datetime(2026, 11, 8, 0, 1, 0, tzinfo=timezone.utc)
    state = detector.update(t_next_day, 2720.0, 2720.20)
    assert state.regime == "RANGE_BOUND"
    assert not state.is_trending
    assert state.day_open_price == 2720.10


def test_regime_detector_orb():
    """Verify Opening Range Breakout logic during London open."""
    detector = MarketRegimeDetector(
        mode="ORB",
        orb_start_hour_utc=7,
        orb_duration_hours=1,
        orb_threshold_usd=3.00,
    )

    t_base = datetime(2026, 11, 7, 6, 30, 0, tzinfo=timezone.utc)
    # Before ORB: RANGE
    s0 = detector.update(t_base, 2700.0, 2700.20)
    assert s0.regime == "RANGE_BOUND"

    # During ORB (07:00 - 08:00 UTC): Accumulating High ($2705) and Low ($2695)
    t_orb_1 = datetime(2026, 11, 7, 7, 15, 0, tzinfo=timezone.utc)
    detector.update(t_orb_1, 2695.0, 2695.20)
    t_orb_2 = datetime(2026, 11, 7, 7, 45, 0, tzinfo=timezone.utc)
    s_orb = detector.update(t_orb_2, 2705.0, 2705.20)
    assert s_orb.regime == "RANGE_BOUND"

    # After ORB (08:05 UTC): ORB is now armed!
    t_post = datetime(2026, 11, 7, 8, 5, 0, tzinfo=timezone.utc)
    s_post = detector.update(t_post, 2700.0, 2700.20)
    assert s_post.orb_active

    # Breakout above ORB High ($2705 + $3.00 = $2708) -> BULLISH TREND!
    t_breakout = datetime(2026, 11, 7, 8, 30, 0, tzinfo=timezone.utc)
    s_breakout = detector.update(t_breakout, 2709.0, 2709.20)
    assert s_breakout.regime == "STRONG_BULLISH_TREND"
    assert s_breakout.is_trending
    assert s_breakout.trend_direction == "BULLISH"


# -------------------------------------------------------------
# 2. Volatility Breakout Scalper & Pyramiding Safety Tests
# -------------------------------------------------------------

def test_volatility_breakout_retest_and_pyramiding_safety():
    """Verify Breakout + Retest entry, and step-by-step pyramiding risk ceiling."""
    scalper = VolatilityBreakoutScalperV1(
        breakout_min_penetration_usd=2.00,
        retest_max_distance_usd=1.50,
        retest_bounce_trigger_usd=0.30,
        hard_sl_offset_usd=1.20,
        pyramid_step_1_usd=2.50,
        pyramid_step_2_usd=3.00,
    )
    portfolio = PortfolioTracker()
    scalper.set_portfolio(portfolio)

    regime_bull = MarketRegimeState(
        regime="STRONG_BULLISH_TREND",
        mode="DYNAMIC_EXPANSION",
        is_trending=True,
        trend_direction="BULLISH",
        day_open_price=2700.0,
        day_expansion_usd=20.0,
        orb_high=2720.0,
        orb_low=2700.0,
        orb_active=True,
        ema_spread=3.0,
        ema_slope=0.20,
    )

    t0 = datetime(2026, 11, 7, 8, 0, 0, tzinfo=timezone.utc)
    ref_high = 2720.0
    ref_low = 2700.0

    # 1. Breakout above ref_high ($2720) by >= $2.00 -> $2722.50
    t1 = t0 + timedelta(minutes=5)
    tick1 = make_tick(t1, 2722.50, 2722.70)
    order1 = scalper.on_tick_with_regime(tick1, regime_bull, ref_high, ref_low)
    assert order1 is None  # No immediate top buying!
    assert scalper.bull_breakout_active

    # 2. Retest pullback towards $2720 (pulls back to $2720.80)
    t2 = t0 + timedelta(minutes=8)
    tick2 = make_tick(t2, 2720.80, 2721.00)
    scalper.on_tick_with_regime(tick2, regime_bull, ref_high, ref_low)
    assert scalper.bull_retest_active

    # 3. Retest Bounce confirmed: rises from $2720.80 to $2721.30 (+0.40+ bounce)
    t3 = t0 + timedelta(minutes=10)
    tick3 = make_tick(t3, 2721.30, 2721.50)
    order_entry = scalper.on_tick_with_regime(tick3, regime_bull, ref_high, ref_low)

    assert order_entry is not None
    assert order_entry.order_type == "OPEN"
    assert order_entry.side == "BUY"
    assert order_entry.volume == 0.05  # Layer 1
    # SL is placed at retest trough ($2720.90 mid) - $1.20 = $2719.70
    assert order_entry.sl == pytest.approx(2719.70, abs=0.01)

    # Simulate position opened in portfolio
    pos_l1 = Position(
        position_id="pos-l1",
        symbol="XAUUSD",
        side="BUY",
        volume=0.05,
        open_time=t3,
        open_price=2721.40,
        sl=order_entry.sl,
    )
    portfolio.open_positions["pos-l1"] = pos_l1

    # 4. Price advances by +$2.60 to $2724.00 (triggers Pyramiding Step 1 -> Layer 2)
    t4 = t0 + timedelta(minutes=15)
    tick4 = make_tick(t4, 2724.00, 2724.20)
    order_l2 = scalper.on_tick_with_regime(tick4, regime_bull, ref_high, ref_low)

    assert order_l2 is not None
    assert order_l2.order_type == "OPEN"
    assert order_l2.volume == 0.10  # Layer 2
    # CRITICAL RISK CEILING: Layer 1 SL MUST be shifted to Breakeven (+0.10)!
    assert pos_l1.sl == pytest.approx(2721.50, abs=0.01)

    # Simulate Layer 2 opened in portfolio
    pos_l2 = Position(
        position_id="pos-l2",
        symbol="XAUUSD",
        side="BUY",
        volume=0.10,
        open_time=t4,
        open_price=2724.10,
        sl=pos_l1.open_price,
    )
    portfolio.open_positions["pos-l2"] = pos_l2

    # 5. Price advances further by +$3.20 to $2727.30 (triggers Pyramiding Step 2 -> Layer 3)
    t5 = t0 + timedelta(minutes=20)
    tick5 = make_tick(t5, 2727.30, 2727.50)
    order_l3 = scalper.on_tick_with_regime(tick5, regime_bull, ref_high, ref_low)

    assert order_l3 is not None
    assert order_l3.order_type == "OPEN"
    assert order_l3.volume == 0.15  # Layer 3
    # GUARANTEED PROFIT LOCK: SL across positions must now lock positive profit!
    assert pos_l1.sl > pos_l1.open_price


# -------------------------------------------------------------
# 3. Adaptive Dual Engine Orchestrator Tests
# -------------------------------------------------------------

def test_adaptive_dual_engine_regime_routing():
    """Verify that AdaptiveDualEngine correctly routes to Engine A in Range and Engine B in Trend."""
    dual = AdaptiveDualEngineScalper(
        regime_mode="DYNAMIC_EXPANSION",
        daily_expansion_threshold_usd=15.00,
        blackout_hours_utc=set(),
    )
    portfolio = PortfolioTracker()
    dual.set_portfolio(portfolio)

    base_time = datetime(2026, 11, 7, 8, 0, 0, tzinfo=timezone.utc)

    # 1. Day open at $2700.00 -> In Range mode
    t1 = base_time
    tick1 = make_tick(t1, 2700.0, 2700.20)
    dual.on_tick(tick1)
    assert not dual.regime_detector._cached_state.is_trending

    # 2. Advance price by +$18.00 -> Enters STRONG_BULLISH_TREND
    t2 = base_time + timedelta(hours=2)
    tick2 = make_tick(t2, 2718.0, 2718.20)
    dual.on_tick(tick2)
    assert dual.regime_detector._cached_state.is_trending
    assert dual.regime_detector._cached_state.trend_direction == "BULLISH"
