"""Flow Momentum & Liquidity Filtered Scalping Strategy for XAUUSD."""

from collections import deque
from datetime import datetime
from typing import Optional, Set

from src.simulator.execution import OrderRequest
from src.strategies.base import BaseStrategy, TickEvent


class FlowMomentumScalper(BaseStrategy):
    """Exploits micro-burst tick arrival velocity and directional delta during peak liquidity."""

    def __init__(
        self,
        name: str = "FlowMomentumScalper",
        window_ticks: int = 25,
        momentum_threshold_usd: float = 0.40,   # $0.40 move across window
        max_elapsed_seconds: float = 3.5,       # Must occur within 3.5 sec (high velocity burst)
        max_spread_usd: float = 0.25,           # Reject if spread > $0.25 (median spread + buffer)
        take_profit_points: float = 0.75,       # $0.75 target
        stop_loss_points: float = 0.50,         # $0.50 stop loss
        max_hold_seconds: float = 90.0,         # Exit after 90 seconds if trade stagnates
        volume: float = 0.50,                   # 0.50 lot size
        max_open_positions: int = 1,
        allowed_hours_utc: Optional[Set[int]] = None,
    ):
        super().__init__(name)
        self.window_ticks = window_ticks
        self.momentum_threshold = momentum_threshold_usd
        self.max_elapsed_seconds = max_elapsed_seconds
        self.max_spread = max_spread_usd
        self.tp_points = take_profit_points
        self.sl_points = stop_loss_points
        self.max_hold_seconds = max_hold_seconds
        self.volume = volume
        self.max_open_positions = max_open_positions

        # Default prime scalping window: 12:00 to 18:00 UTC (19:00 to 01:00 WIB - US & London overlap)
        self.allowed_hours_utc = allowed_hours_utc if allowed_hours_utc is not None else {12, 13, 14, 15, 16, 17, 18}

        self.price_history: deque[float] = deque(maxlen=window_ticks)
        self.time_history: deque[datetime] = deque(maxlen=window_ticks)

    def on_tick(self, tick: TickEvent) -> Optional[OrderRequest]:
        mid_price = (tick.bid + tick.ask) / 2.0
        self.price_history.append(mid_price)
        self.time_history.append(tick.timestamp)

        # -------------------------------------------------------------
        # 1. Check Time Stop for Open Positions
        # -------------------------------------------------------------
        if self.portfolio and self.portfolio.open_positions:
            for pos_id, pos in list(self.portfolio.open_positions.items()):
                hold_duration = (tick.timestamp - pos.open_time).total_seconds()
                if hold_duration >= self.max_hold_seconds:
                    close_side = "SELL" if pos.side == "BUY" else "BUY"
                    return OrderRequest(
                        order_type="CLOSE",
                        side=close_side,
                        volume=pos.volume,
                        signal_time=tick.timestamp,
                        target_position_id=pos_id,
                        reason="TIME_STOP",
                    )
            # If position open and not timed out, do not open new position
            if len(self.portfolio.open_positions) >= self.max_open_positions:
                return None

        # -------------------------------------------------------------
        # 2. Execution Gating Filters (Spread & Session Hour)
        # -------------------------------------------------------------
        # Hour filter
        if tick.timestamp.hour not in self.allowed_hours_utc:
            return None

        # Spread filter
        if tick.spread > self.max_spread:
            return None

        # Need full window
        if len(self.price_history) < self.window_ticks:
            return None

        # -------------------------------------------------------------
        # 3. Micro Tick Velocity & Directional Flow Evaluation
        # -------------------------------------------------------------
        elapsed_sec = (self.time_history[-1] - self.time_history[0]).total_seconds()
        if elapsed_sec > self.max_elapsed_seconds or elapsed_sec <= 0:
            return None  # Tick velocity too slow, not a sharp momentum burst

        delta_price = self.price_history[-1] - self.price_history[0]

        # Bullish Liquidity Absorption Burst
        if delta_price >= self.momentum_threshold:
            self.price_history.clear()
            self.time_history.clear()
            return OrderRequest(
                order_type="OPEN",
                side="BUY",
                volume=self.volume,
                signal_time=tick.timestamp,
                sl=round(tick.ask - self.sl_points, 3),
                tp=round(tick.ask + self.tp_points, 3),
                reason="FLOW_BUY_BURST",
            )

        # Bearish Liquidity Absorption Burst
        elif delta_price <= -self.momentum_threshold:
            self.price_history.clear()
            self.time_history.clear()
            return OrderRequest(
                order_type="OPEN",
                side="SELL",
                volume=self.volume,
                signal_time=tick.timestamp,
                sl=round(tick.bid + self.sl_points, 3),
                tp=round(tick.bid - self.tp_points, 3),
                reason="FLOW_SELL_BURST",
            )

        return None
