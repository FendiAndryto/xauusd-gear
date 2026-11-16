"""Unit tests for LayerManager (TICK-302)."""

from datetime import datetime, timezone
import pytest

from src.simulator.layer_manager import LayerManager
from src.simulator.portfolio import PortfolioTracker
from src.strategies.base import TickEvent


def test_layer_manager_lifecycle():
    mgr = LayerManager(layer_volumes=[0.05, 0.10, 0.15], layer_spacing_usd=0.40)
    portfolio = PortfolioTracker()
    t0 = datetime(2026, 10, 1, 14, 0, 0, tzinfo=timezone.utc)

    # 1. Start SELL setup at 2655.00, Hard SL at 2656.50, TP1 at 2652.50, TP2 at 2650.00
    req1 = mgr.start_setup(
        side="SELL",
        timestamp=t0,
        hard_sl=2656.50,
        tp1_price=2652.50,
        tp2_price=2650.00,
    )
    assert req1.volume == 0.05
    assert req1.side == "SELL"
    assert mgr.has_active_setup is True

    # Register Layer 1 in portfolio
    pos1 = portfolio.open_position("SELL", 0.05, 2655.00, t0, sl=2656.50, tp=2650.00)
    mgr.register_position(pos1.position_id)

    # 2. Price pulls back up to 2655.45 (adverse distance = 0.45 >= 0.40) -> Layer 2 Trigger!
    t1 = datetime(2026, 10, 1, 14, 0, 10, tzinfo=timezone.utc)
    tick_retest = TickEvent(t1, bid=2655.20, ask=2655.45, spread=0.25, volume=1.0, flags=6)
    orders = mgr.evaluate(tick_retest, portfolio)

    assert len(orders) == 1
    req2 = orders[0]
    assert req2.volume == 0.10
    assert req2.reason == "LAYER_2_SELL_RETEST"

    # Register Layer 2 in portfolio
    pos2 = portfolio.open_position("SELL", 0.10, 2655.45, t1, sl=2656.50, tp=2650.00)
    mgr.register_position(pos2.position_id)

    # 3. Price pulls back further up to 2655.85 (adverse distance = 0.85 >= 0.80) -> Layer 3 Trigger!
    t2 = datetime(2026, 10, 1, 14, 0, 20, tzinfo=timezone.utc)
    tick_extreme = TickEvent(t2, bid=2655.60, ask=2655.85, spread=0.25, volume=1.0, flags=6)
    orders3 = mgr.evaluate(tick_extreme, portfolio)

    assert len(orders3) == 1
    req3 = orders3[0]
    assert req3.volume == 0.15
    assert req3.reason == "LAYER_3_SELL_EXTREME"

    # Register Layer 3 in portfolio
    pos3 = portfolio.open_position("SELL", 0.15, 2655.85, t2, sl=2656.50, tp=2650.00)
    mgr.register_position(pos3.position_id)

    # Verify no Layer 4 can be created
    t3 = datetime(2026, 10, 1, 14, 0, 25, tzinfo=timezone.utc)
    tick_more = TickEvent(t3, bid=2655.90, ask=2656.15, spread=0.25, volume=1.0, flags=6)
    assert len(mgr.evaluate(tick_more, portfolio)) == 0

    # 4. HARD SL HIT: Price spikes to 2656.55 >= Hard SL 2656.50
    t4 = datetime(2026, 10, 1, 14, 0, 30, tzinfo=timezone.utc)
    tick_sl = TickEvent(t4, bid=2656.30, ask=2656.55, spread=0.25, volume=1.0, flags=6)
    sl_orders = mgr.evaluate(tick_sl, portfolio)

    # MUST liquidate ALL 3 layers simultaneously
    assert len(sl_orders) == 3
    for o in sl_orders:
        assert o.order_type == "CLOSE"
        assert o.reason == "HARD_INVALIDATION_SL"
    assert mgr.has_active_setup is False


def test_layer_manager_be_policy_strict():
    mgr = LayerManager(layer_volumes=[0.05, 0.10, 0.15], be_policy="STRICT")
    portfolio = PortfolioTracker()
    t0 = datetime(2026, 10, 1, 14, 0, 0, tzinfo=timezone.utc)

    # SELL setup at entry 2655.00, SL 2657.00, TP1 2652.50, TP2 2650.00
    mgr.start_setup(side="SELL", timestamp=t0, hard_sl=2657.00, tp1_price=2652.50, tp2_price=2650.00)
    pos1 = portfolio.open_position("SELL", 0.05, 2655.00, t0, sl=2657.00, tp=2650.00)
    mgr.register_position(pos1.position_id)

    # Price hits TP1 (2652.40 <= 2652.50)
    t1 = datetime(2026, 10, 1, 14, 2, 0, tzinfo=timezone.utc)
    tick_tp1 = TickEvent(t1, bid=2652.40, ask=2652.64, spread=0.24, volume=1.0, flags=6)
    mgr.evaluate(tick_tp1, portfolio)

    # In STRICT policy, hard_sl must be moved to entry price (2655.00)
    assert mgr.current_setup.hard_sl == 2655.00
    assert portfolio.open_positions[pos1.position_id].sl == 2655.00


def test_layer_manager_be_policy_buffer():
    mgr = LayerManager(layer_volumes=[0.05, 0.10, 0.15], be_policy="BUFFER")
    portfolio = PortfolioTracker()
    t0 = datetime(2026, 10, 1, 14, 0, 0, tzinfo=timezone.utc)

    # SELL setup with boundary_price at 2654.50 (RH), hard_sl at 2657.00
    mgr.start_setup(
        side="SELL",
        timestamp=t0,
        hard_sl=2657.00,
        tp1_price=2652.50,
        tp2_price=2650.00,
        boundary_price=2654.50,
    )
    pos1 = portfolio.open_position("SELL", 0.05, 2655.00, t0, sl=2657.00, tp=2650.00)
    mgr.register_position(pos1.position_id)

    # Price hits TP1
    t1 = datetime(2026, 10, 1, 14, 2, 0, tzinfo=timezone.utc)
    tick_tp1 = TickEvent(t1, bid=2652.40, ask=2652.64, spread=0.24, volume=1.0, flags=6)
    mgr.evaluate(tick_tp1, portfolio)

    # In BUFFER policy, hard_sl must be moved to boundary + 0.15 = 2654.65
    assert mgr.current_setup.hard_sl == 2654.65


def test_layer_manager_session_sizing():
    mgr = LayerManager(layer_volumes=[0.05, 0.10, 0.15])
    t0 = datetime(2026, 10, 1, 2, 0, 0, tzinfo=timezone.utc)

    # Asian session: 50% lot multiplier, max 2 layers
    req = mgr.start_setup(
        side="BUY",
        timestamp=t0,
        hard_sl=2645.00,
        tp1_price=2648.00,
        tp2_price=2650.00,
        lot_multiplier=0.50,
        max_layers=2,
    )

    assert req.volume == 0.03  # 0.05 * 0.50 = 0.025 rounded to 0.03 or max(0.01)
    assert mgr.current_setup.current_max_layers == 2
