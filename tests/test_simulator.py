"""Tests for reality simulator: portfolio, execution model, and backtest engine."""

from datetime import datetime, timezone
import polars as pl
import pytest

from src.config import BacktestConfig, BrokerConfig
from src.ingestion.schema import TICK_SCHEMA
from src.simulator.engine import TickBacktestEngine
from src.simulator.execution import ExecutionModel, OrderRequest
from src.simulator.portfolio import PortfolioTracker
from src.strategies.base import BaseStrategy, TickEvent


def test_portfolio_buy_pnl():
    portfolio = PortfolioTracker(initial_balance=10_000.0)
    t0 = datetime(2024, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 10, 1, 10, 5, 0, tzinfo=timezone.utc)

    # Open Buy 1.0 lot at 2650.00 (half commission $3.00)
    pos = portfolio.open_position("BUY", volume=1.0, price=2650.00, timestamp=t0, commission=3.0)
    assert pos.is_open

    # Close at 2652.00 (additional commission $3.00)
    # Gross = (2652 - 2650) * 100 * 1.0 = +$200.00
    # Net = 200 - 6 = +$194.00
    closed = portfolio.close_position(pos.position_id, price=2652.00, timestamp=t1, additional_commission=3.0)
    assert not closed.is_open
    assert closed.pnl_gross == 200.00
    assert closed.pnl_net == 194.00
    assert portfolio.balance == 10_194.00


def test_portfolio_sell_pnl():
    portfolio = PortfolioTracker(initial_balance=10_000.0)
    t0 = datetime(2024, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 10, 1, 10, 5, 0, tzinfo=timezone.utc)

    # Open Sell 0.5 lot at 2650.00
    pos = portfolio.open_position("SELL", volume=0.5, price=2650.00, timestamp=t0, commission=1.5)
    # Close at 2648.00 (profitable short)
    # Gross = (2650 - 2648) * 100 * 0.5 = +$100.00
    # Net = 100 - 3 = +$97.00
    closed = portfolio.close_position(pos.position_id, price=2648.00, timestamp=t1, additional_commission=1.5)
    assert closed.pnl_gross == 100.00
    assert closed.pnl_net == 97.00
    assert portfolio.balance == 10_097.00


def test_execution_reality_spread_and_slippage():
    exec_model = ExecutionModel(random_seed=123)
    t0 = datetime(2024, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
    req = OrderRequest(order_type="OPEN", side="BUY", volume=1.0, signal_time=t0)
    
    pending = exec_model.queue_order(req)
    assert pending.executable_after > t0  # Latency buffer applied

    # Buy fills at ask + slippage
    ask = 2650.50
    bid = 2650.25
    res = exec_model.execute_fill(pending, pending.executable_after, bid, ask)
    assert res.fill_price >= ask
    assert res.slippage_points >= 0.0


class SimpleTriggerStrategy(BaseStrategy):
    """Buys once at start, sets TP and SL."""
    def __init__(self):
        super().__init__("SimpleTrigger")
        self.has_entered = False

    def on_tick(self, tick: TickEvent):
        if not self.has_entered:
            self.has_entered = True
            return OrderRequest(
                order_type="OPEN",
                side="BUY",
                volume=1.0,
                signal_time=tick.timestamp,
                sl=2648.00,
                tp=2655.00,
            )
        return None


def test_engine_event_loop_tp_trigger():
    strategy = SimpleTriggerStrategy()
    engine = TickBacktestEngine(strategy=strategy)

    # Generate synthetic ticks where TP is reached
    ticks_df = pl.DataFrame({
        "timestamp": [
            datetime(2024, 10, 1, 10, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2024, 10, 1, 10, 0, 0, 200_000, tzinfo=timezone.utc),  # Executed here (after 50-150ms delay)
            datetime(2024, 10, 1, 10, 0, 1, 0, tzinfo=timezone.utc),        # Price spikes to TP
        ],
        "bid": [2650.00, 2650.10, 2656.00],  # 2656 > 2655 TP!
        "ask": [2650.25, 2650.35, 2656.25],
        "spread": [0.25, 0.25, 0.25],
        "volume": [1.0, 1.0, 1.0],
        "flags": [6, 6, 6],
    }).cast(TICK_SCHEMA)

    res = engine.run(ticks_df, snapshot_interval_ticks=1)

    assert len(res.closed_trades) == 1
    trade = res.closed_trades[0]
    assert trade.close_reason == "TP"
    assert trade.pnl_net > 0  # Winning trade
    assert res.portfolio.balance > 10_000.0
