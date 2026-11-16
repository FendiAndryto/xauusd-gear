"""High-performance Tick Event-Driven Simulation Engine for XAUUSD Scalping."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import numpy as np
import polars as pl

from src.config import BacktestConfig
from src.simulator.execution import ExecutionModel, OrderRequest, PendingOrder
from src.simulator.portfolio import AccountSnapshot, PortfolioTracker, Position
from src.strategies.base import BaseStrategy, TickEvent


@dataclass
class SimulationResult:
    """Output container for a completed backtest run."""
    portfolio: PortfolioTracker
    closed_trades: list[Position]
    equity_curve: list[AccountSnapshot]
    total_ticks_processed: int
    execution_time_seconds: float


class TickBacktestEngine:
    """Core event-driven simulator iterating tick-by-tick with realistic execution physics."""

    def __init__(self, strategy: BaseStrategy, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
        self.strategy = strategy
        self.portfolio = PortfolioTracker(
            initial_balance=self.config.initial_balance,
            broker_config=self.config.broker,
        )
        self.execution = ExecutionModel(
            broker_config=self.config.broker,
            exec_config=self.config.execution,
        )
        self.pending_orders: list[PendingOrder] = []
        self.strategy.set_portfolio(self.portfolio)

    def run(self, ticks_df: pl.DataFrame, snapshot_interval_ticks: int = 1000) -> SimulationResult:
        """Run the simulation over a Polars DataFrame of real ticks.
        
        Args:
            ticks_df: DataFrame adhering to TICK_SCHEMA.
            snapshot_interval_ticks: Interval in ticks to record equity curve snapshots.
            
        Returns:
            SimulationResult containing trade history and equity curve.
        """
        import time
        start_wall_time = time.time()

        if ticks_df.is_empty():
            raise ValueError("ticks_df is empty. Cannot run backtest.")

        self.strategy.on_start()

        # Convert Polars columns to fast native Python lists / numpy arrays
        timestamps = ticks_df["timestamp"].to_list()
        bids = ticks_df["bid"].to_numpy()
        asks = ticks_df["ask"].to_numpy()
        spreads = ticks_df["spread"].to_numpy()
        volumes = ticks_df["volume"].to_numpy()
        flags = ticks_df["flags"].to_numpy()

        total_ticks = len(timestamps)

        for i in range(total_ticks):
            t_time: datetime = timestamps[i]
            t_bid: float = float(bids[i])
            t_ask: float = float(asks[i])
            t_spread: float = float(spreads[i])
            t_vol: float = float(volumes[i])
            t_flag: int = int(flags[i])

            # -------------------------------------------------------------
            # 1. Evaluate SL / TP triggers on existing open positions
            # -------------------------------------------------------------
            self._evaluate_stops(t_time, t_bid, t_ask)

            # -------------------------------------------------------------
            # 2. Process Pending Queue (Orders delayed by simulated latency)
            # -------------------------------------------------------------
            self._process_pending_queue(t_time, t_bid, t_ask)

            # -------------------------------------------------------------
            # 3. Deliver Tick Event to Strategy & Queue New Signals
            # -------------------------------------------------------------
            tick_event = TickEvent(
                timestamp=t_time,
                bid=t_bid,
                ask=t_ask,
                spread=t_spread,
                volume=t_vol,
                flags=t_flag,
            )
            signal: Optional[OrderRequest] = self.strategy.on_tick(tick_event)
            if signal is not None:
                # Filter abnormal spreads before queuing entry orders
                if signal.order_type == "OPEN" and t_spread > self.config.execution.max_tolerated_spread_points:
                    pass  # Skip signal due to abnormal spread spike
                else:
                    pending = self.execution.queue_order(signal)
                    self.pending_orders.append(pending)

            # -------------------------------------------------------------
            # 4. Periodic Equity Curve Snapshot
            # -------------------------------------------------------------
            if i % snapshot_interval_ticks == 0 or i == total_ticks - 1:
                snap = self.portfolio.update_tick(t_time, t_bid, t_ask)
                self.portfolio.equity_history.append(snap)

        # Close any lingering open positions at end of backtest at final tick
        final_time = timestamps[-1]
        final_bid = float(bids[-1])
        final_ask = float(asks[-1])
        self._close_all_open_positions(final_time, final_bid, final_ask, reason="END_OF_TEST")

        self.strategy.on_finish()
        elapsed = time.time() - start_wall_time

        return SimulationResult(
            portfolio=self.portfolio,
            closed_trades=self.portfolio.closed_positions,
            equity_curve=self.portfolio.equity_history,
            total_ticks_processed=total_ticks,
            execution_time_seconds=elapsed,
        )

    def _evaluate_stops(self, current_time: datetime, current_bid: float, current_ask: float):
        """Check all open positions against Stop Loss and Take Profit levels."""
        open_ids = list(self.portfolio.open_positions.keys())
        for pos_id in open_ids:
            if pos_id not in self.portfolio.open_positions:
                continue
            pos = self.portfolio.open_positions[pos_id]

            if pos.side == "BUY":
                # BUY closes at Bid
                if pos.sl is not None and current_bid <= pos.sl:
                    # SL hit with negative slippage
                    fill_price = current_bid - self.config.execution.base_slippage_mean_points
                    comm = (self.config.broker.commission_per_lot_round_turn / 2.0) * pos.volume
                    self.portfolio.close_position(pos_id, fill_price, current_time, reason="SL", additional_commission=comm)
                elif pos.tp is not None and current_bid >= pos.tp:
                    # TP hit
                    comm = (self.config.broker.commission_per_lot_round_turn / 2.0) * pos.volume
                    self.portfolio.close_position(pos_id, pos.tp, current_time, reason="TP", additional_commission=comm)

            elif pos.side == "SELL":
                # SELL closes at Ask
                if pos.sl is not None and current_ask >= pos.sl:
                    # SL hit with negative slippage
                    fill_price = current_ask + self.config.execution.base_slippage_mean_points
                    comm = (self.config.broker.commission_per_lot_round_turn / 2.0) * pos.volume
                    self.portfolio.close_position(pos_id, fill_price, current_time, reason="SL", additional_commission=comm)
                elif pos.tp is not None and current_ask <= pos.tp:
                    # TP hit
                    comm = (self.config.broker.commission_per_lot_round_turn / 2.0) * pos.volume
                    self.portfolio.close_position(pos_id, pos.tp, current_time, reason="TP", additional_commission=comm)

    def _process_pending_queue(self, current_time: datetime, current_bid: float, current_ask: float):
        """Execute orders whose simulated network latency delay has elapsed."""
        remaining_pending = []
        for pending in self.pending_orders:
            if current_time >= pending.executable_after:
                req = pending.request
                fill = self.execution.execute_fill(pending, current_time, current_bid, current_ask)

                if req.order_type == "OPEN":
                    self.portfolio.open_position(
                        side=req.side,
                        volume=req.volume,
                        price=fill.fill_price,
                        timestamp=current_time,
                        sl=req.sl,
                        tp=req.tp,
                        commission=fill.commission,
                        comment=req.reason,
                    )
                elif req.order_type == "CLOSE" and req.target_position_id:
                    if req.target_position_id in self.portfolio.open_positions:
                        self.portfolio.close_position(
                            position_id=req.target_position_id,
                            price=fill.fill_price,
                            timestamp=current_time,
                            reason=req.reason,
                            additional_commission=fill.commission,
                        )
            else:
                remaining_pending.append(pending)
        self.pending_orders = remaining_pending

    def _close_all_open_positions(self, current_time: datetime, current_bid: float, current_ask: float, reason: str):
        """Liquidate remaining positions at final tick."""
        open_ids = list(self.portfolio.open_positions.keys())
        for pos_id in open_ids:
            pos = self.portfolio.open_positions[pos_id]
            price = current_bid if pos.side == "BUY" else current_ask
            comm = (self.config.broker.commission_per_lot_round_turn / 2.0) * pos.volume
            self.portfolio.close_position(pos_id, price, current_time, reason=reason, additional_commission=comm)
