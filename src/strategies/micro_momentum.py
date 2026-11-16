"""Micro-Momentum & Order Flow Imbalance Scalping Strategy for XAUUSD."""

from collections import deque
from datetime import datetime
from typing import Optional

from src.simulator.execution import OrderRequest
from src.strategies.base import BaseStrategy, TickEvent


class MicroMomentumScalper(BaseStrategy):
    """Scalping strategy targeting sub-second price momentum bursts on tight spreads."""

    def __init__(
        self,
        name: str = "MicroMomentum",
        window_size: int = 20,
        momentum_threshold_usd: float = 0.35,  # $0.35 price move over window
        max_spread_usd: float = 0.30,           # Only enter on tight spread
        take_profit_points: float = 0.80,       # $0.80 target
        stop_loss_points: float = 0.60,         # $0.60 stop loss
        volume: float = 0.50,                   # 0.50 lot
        max_open_positions: int = 1,
    ):
        super().__init__(name)
        self.window_size = window_size
        self.momentum_threshold = momentum_threshold_usd
        self.max_spread = max_spread_usd
        self.tp_points = take_profit_points
        self.sl_points = stop_loss_points
        self.volume = volume
        self.max_open_positions = max_open_positions
        self.history: deque[float] = deque(maxlen=window_size)

    def on_tick(self, tick: TickEvent) -> Optional[OrderRequest]:
        # Track mid price
        mid_price = (tick.bid + tick.ask) / 2.0
        self.history.append(mid_price)

        # Cannot trade if position limit reached
        if self.portfolio and len(self.portfolio.open_positions) >= self.max_open_positions:
            return None

        # Need full window
        if len(self.history) < self.window_size:
            return None

        # Filter abnormal spreads
        if tick.spread > self.max_spread:
            return None

        # Calculate momentum delta over window
        delta = self.history[-1] - self.history[0]

        # Bullish Burst: Price pushed up rapidly
        if delta >= self.momentum_threshold:
            self.history.clear()  # reset after firing signal
            return OrderRequest(
                order_type="OPEN",
                side="BUY",
                volume=self.volume,
                signal_time=tick.timestamp,
                sl=round(tick.ask - self.sl_points, 2),
                tp=round(tick.ask + self.tp_points, 2),
                reason="MOMENTUM_BUY",
            )

        # Bearish Burst: Price pushed down rapidly
        elif delta <= -self.momentum_threshold:
            self.history.clear()
            return OrderRequest(
                order_type="OPEN",
                side="SELL",
                volume=self.volume,
                signal_time=tick.timestamp,
                sl=round(tick.bid + self.sl_points, 2),
                tp=round(tick.bid - self.tp_points, 2),
                reason="MOMENTUM_SELL",
            )

        return None
