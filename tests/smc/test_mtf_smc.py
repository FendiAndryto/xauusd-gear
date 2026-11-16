"""Unit & Integration Tests for Standalone MTF SMC Scalper Architecture."""

from datetime import date, datetime, timedelta
import pytest

from src.simulator.portfolio import PortfolioTracker
from src.strategies.base import TickEvent
from src.strategies.smc.d1_boundary_extractor import D1BoundaryExtractor, DailyBar
from src.strategies.smc.h1_bias_classifier import H1BiasClassifier, H1Bar, BiasDirection
from src.strategies.smc.sweep_acceptance_engine import SweepAcceptanceEngine, ReactionType, M5Bar
from src.strategies.smc.order_block_mapper import OrderBlockMapper, ObType
from src.strategies.smc.pyramid_limit_manager import PyramidLimitManager
from src.strategies.smc.daily_financial_guard import DailyFinancialGuard, GuardState, TradingSession
from src.strategies.smc.mtf_smc_scalper import MtfSmcScalper


def test_d1_recursive_mother_bar_fallback():
    """Verify inside days recursively climb back to find the parent mother bar."""
    bars = [
        # Day 1: Mother Bar (Range: 2600 to 2650)
        DailyBar(bar_date=date(2026, 4, 1), open=2610, high=2650, low=2600, close=2640),
        # Day 2: Inside Bar 1 (Range: 2610 to 2640 - inside Day 1)
        DailyBar(bar_date=date(2026, 4, 2), open=2620, high=2640, low=2610, close=2630),
        # Day 3: Inside Bar 2 (Range: 2615 to 2635 - inside Day 2 & Day 1)
        DailyBar(bar_date=date(2026, 4, 3), open=2625, high=2635, low=2615, close=2628),
    ]

    extractor = D1BoundaryExtractor(historical_days=bars)
    boundary = extractor.active_boundary

    assert boundary is not None
    assert boundary.is_inside_fallback is True
    # Boundary must resolve to Day 1 (Mother Bar)
    assert boundary.pdh == 2650.0
    assert boundary.pdl == 2600.0
    assert boundary.equilibrium == 2625.0
    assert boundary.mother_bar_date == date(2026, 4, 1)


def test_h1_bias_classifier():
    """Verify H1 bias classifies bullish and bearish structure correctly."""
    classifier = H1BiasClassifier(ema_period=5)
    
    # Sequence of rising H1 bars
    t = datetime(2026, 4, 1, 0, 0)
    bars = []
    price = 2600.0
    for i in range(10):
        bars.append(H1Bar(
            start_time=t + timedelta(hours=i),
            open=price,
            high=price + 5.0,
            low=price - 1.0,
            close=price + 4.0,
        ))
        price += 4.0

    classifier.seed_h1_bars(bars)
    assert classifier.current_bias == BiasDirection.BULLISH


def test_sweep_rejection_at_pdh():
    """Verify M5 bar testing PDH with long upper wick produces SWEEP_REJECTION_PDH."""
    bars = [
        DailyBar(bar_date=date(2026, 4, 1), open=2600, high=2650, low=2600, close=2630),
    ]
    extractor = D1BoundaryExtractor(historical_days=bars)
    boundary = extractor.active_boundary
    assert boundary is not None

    engine = SweepAcceptanceEngine(min_wick_ratio=0.40)

    # Bar sweeps above 2650 up to 2655, but closes back at 2648 with long upper wick
    swept_bar = M5Bar(
        start_time=datetime(2026, 4, 2, 10, 0),
        open=2645.0,
        high=2655.0,  # Swept PDH 2650
        low=2644.0,
        close=2648.0,  # Closed below 2650
    )

    rx, extreme = engine.evaluate_bar(swept_bar, boundary)
    assert rx == ReactionType.SWEEP_REJECTION_PDH
    assert extreme == 2655.0


def test_order_block_mapping_and_pyramid_limits():
    """Verify Order Block mapping and layered pyramid order creation."""
    ob_mapper = OrderBlockMapper()

    # Pre-populate bar history with a swing low at 2642
    t = datetime(2026, 4, 2, 10, 0)
    ob_mapper.bars = [
        M5Bar(start_time=t - timedelta(minutes=20), open=2644, high=2647, low=2642, close=2645),
        M5Bar(start_time=t - timedelta(minutes=15), open=2645, high=2652, low=2644, close=2650),
        M5Bar(start_time=t - timedelta(minutes=10), open=2650, high=2655, low=2648, close=2652),  # Bullish candle before drop
    ]
    ob_mapper.recent_swing_low = 2644.0

    # Displacement down candle breaking below 2644 (Bearish CHoCH)
    choch_bar = M5Bar(
        start_time=t - timedelta(minutes=5),
        open=2652.0,
        high=2653.0,
        low=2639.0,
        close=2640.0,  # Breaks below swing low 2644
    )

    choch = ob_mapper.on_bar_completed(
        choch_bar,
        ReactionType.SWEEP_REJECTION_PDH,
        sweep_extreme=2655.0,
    )

    assert choch is not None
    assert choch.direction == "BEARISH"
    assert choch.order_block.side == "SELL"
    assert choch.order_block.extreme_wick_sl == 2655.0

    # Test Pyramid Limit creation
    limit_mgr = PyramidLimitManager(
        risk_layer1_pct=0.010,
        risk_layer2_pct=0.015,
        spread_buffer_usd=0.25,
    )

    orders = limit_mgr.create_pyramid_orders(
        ob=choch.order_block,
        current_time=t,
        equity=10_000.0,
        equilibrium_tp=2625.0,
        opposite_boundary_tp=2600.0,
    )

    # Must create 4 sub-orders (Layer 1 TP1 & Runner, Layer 2 TP1 & Runner)
    assert len(orders) == 4
    # All must share extreme wick SL bounded by max scalp SL ($3.50)
    for o in orders:
        assert o.sl == 2653.50
        assert o.side == "SELL"


def test_daily_financial_guard_circuit_breakers():
    """Verify Daily Profit Cap (+10%) and Daily Drawdown (-10%) Circuit Breakers."""
    portfolio = PortfolioTracker(initial_balance=10_000.0)
    guard = DailyFinancialGuard(daily_profit_cap_pct=0.10, daily_loss_limit_pct=0.10)

    t = datetime(2026, 4, 2, 8, 0)

    # 1. Normal state
    state = guard.on_tick(t, current_spread=0.15, portfolio=portfolio)
    assert state == GuardState.ACTIVE

    # 2. Spread spike state
    state = guard.on_tick(t, current_spread=0.45, portfolio=portfolio)
    assert state == GuardState.SPREAD_TOO_HIGH

    # 3. Profit Cap reached (+10%)
    portfolio.balance = 11_050.0  # +$1.050 profit (+10.5%)
    state = guard.on_tick(t, current_spread=0.15, portfolio=portfolio)
    assert state == GuardState.DAILY_CAP_REACHED

    # 4. Circuit Breaker tripped (-10%)
    portfolio_cb = PortfolioTracker(initial_balance=10_000.0)
    guard_loss = DailyFinancialGuard(daily_loss_limit_pct=0.10)
    guard_loss.on_tick(t, current_spread=0.15, portfolio=portfolio_cb)  # Initialize start of day at $10.000

    portfolio_cb.balance = 8_900.0  # -$1.100 loss (-11%) later in the day
    state = guard_loss.on_tick(t, current_spread=0.15, portfolio=portfolio_cb)
    assert state == GuardState.CIRCUIT_BREAKER_TRIPPED


def test_trading_sessions_tagging():
    """Verify session categorization."""
    assert DailyFinancialGuard.get_session(datetime(2026, 4, 2, 3, 0)) == TradingSession.ASIA
    assert DailyFinancialGuard.get_session(datetime(2026, 4, 2, 9, 0)) == TradingSession.LONDON
    assert DailyFinancialGuard.get_session(datetime(2026, 4, 2, 15, 0)) == TradingSession.NEW_YORK
    assert DailyFinancialGuard.get_session(datetime(2026, 4, 2, 22, 0)) == TradingSession.ROLLOVER


def test_mtf_smc_scalper_e2e_with_engine():
    """Verify MtfSmcScalper running inside TickBacktestEngine with tick events."""
    import polars as pl
    from src.simulator.engine import TickBacktestEngine
    from src.config import BacktestConfig

    strategy = MtfSmcScalper(
        daily_profit_cap_pct=0.10,
        daily_loss_limit_pct=0.10,
        risk_layer1_pct=0.01,
        risk_layer2_pct=0.015,
        max_spread_pips=3.5,
    )

    engine = TickBacktestEngine(strategy=strategy, config=BacktestConfig(initial_balance=10_000.0))

    # Build synthetic tick series
    times = []
    bids = []
    asks = []
    spreads = []
    vols = []
    flags = []

    # Day 1: 2026-04-01: Establish D1 range 2600 to 2650
    t = datetime(2026, 4, 1, 0, 0)
    for i in range(100):
        t += timedelta(minutes=14)
        p = 2600.0 + (50.0 * (i / 100.0))
        times.append(t)
        bids.append(p)
        asks.append(p + 0.15)
        spreads.append(0.15)
        vols.append(1.0)
        flags.append(0)

    # Day 2: 2026-04-02: Rollover to new day
    t = datetime(2026, 4, 2, 0, 1)
    # Price hovers around 2640, then surges to sweep 2655, then dumps to 2630
    for p in [2640, 2642, 2645, 2652, 2655, 2648, 2642, 2638, 2635, 2630]:
        t += timedelta(minutes=5)
        times.append(t)
        bids.append(float(p))
        asks.append(float(p) + 0.15)
        spreads.append(0.15)
        vols.append(1.0)
        flags.append(0)

    df = pl.DataFrame({
        "timestamp": times,
        "bid": bids,
        "ask": asks,
        "spread": spreads,
        "volume": vols,
        "flags": flags,
    })

    result = engine.run(df)
    assert result.total_ticks_processed == len(times)
    assert result.portfolio.balance > 0
    assert result.execution_time_seconds >= 0.0
