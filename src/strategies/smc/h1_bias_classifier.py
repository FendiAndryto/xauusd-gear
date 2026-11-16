"""TICK-SMC-02: H1 Order Flow & Directional Bias Classifier.

Aggregates 1-hour bars on the fly from ticks, computes EMA 20 and market structure,
and determines directional bias (BULLISH, BEARISH, NEUTRAL).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class BiasDirection(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class H1Bar:
    """Represents a 1-hour OHLC bar."""
    start_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class H1BiasClassifier:
    """Streaming H1 order flow and trend direction classifier."""

    def __init__(self, ema_period: int = 20, max_history: int = 100):
        self.ema_period = ema_period
        self.max_history = max_history
        self.bars: list[H1Bar] = []
        self.current_bar: Optional[H1Bar] = None
        self.ema_value: Optional[float] = None
        self.current_bias: BiasDirection = BiasDirection.NEUTRAL

    def on_tick(self, timestamp: datetime, price: float, volume: float = 1.0) -> BiasDirection:
        """Stream tick, build H1 bar, and update directional bias."""
        bar_start = timestamp.replace(minute=0, second=0, microsecond=0)

        if self.current_bar is None:
            self.current_bar = H1Bar(
                start_time=bar_start,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
            )
            return self.current_bias

        if bar_start > self.current_bar.start_time:
            # New hour rolled over: finalize previous bar
            self.bars.append(self.current_bar)
            if len(self.bars) > self.max_history:
                self.bars.pop(0)

            self._update_ema(self.current_bar.close)
            self._evaluate_bias()

            # Start new bar
            self.current_bar = H1Bar(
                start_time=bar_start,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
            )
        else:
            # Update current in-progress H1 bar
            self.current_bar.high = max(self.current_bar.high, price)
            self.current_bar.low = min(self.current_bar.low, price)
            self.current_bar.close = price
            self.current_bar.volume += volume

        return self.current_bias

    def seed_h1_bars(self, bars: list[H1Bar]):
        """Seed classifier with historical H1 bars."""
        self.bars = list(bars)
        if len(self.bars) >= self.ema_period:
            # Seed initial EMA
            close_prices = [b.close for b in self.bars]
            k = 2.0 / (self.ema_period + 1)
            ema = close_prices[0]
            for c in close_prices[1:]:
                ema = (c * k) + (ema * (1 - k))
            self.ema_value = ema
            self._evaluate_bias()

    def _update_ema(self, close_price: float):
        """Update EMA 20 with new bar close."""
        k = 2.0 / (self.ema_period + 1)
        if self.ema_value is None:
            self.ema_value = close_price
        else:
            self.ema_value = (close_price * k) + (self.ema_value * (1 - k))

    def _evaluate_bias(self):
        """Classify bias based on price vs EMA20 and higher-high / lower-low structure."""
        if len(self.bars) < 3 or self.ema_value is None:
            self.current_bias = BiasDirection.NEUTRAL
            return

        last_close = self.bars[-1].close
        prev_close = self.bars[-2].close
        
        # Check swing highs and swing lows across last 5 bars
        lookback = min(5, len(self.bars))
        recent_bars = self.bars[-lookback:]
        
        highs = [b.high for b in recent_bars]
        lows = [b.low for b in recent_bars]
        
        is_bullish_structure = highs[-1] >= highs[0] and lows[-1] >= lows[0]
        is_bearish_structure = highs[-1] <= highs[0] and lows[-1] <= lows[0]

        if last_close > self.ema_value and is_bullish_structure:
            self.current_bias = BiasDirection.BULLISH
        elif last_close < self.ema_value and is_bearish_structure:
            self.current_bias = BiasDirection.BEARISH
        elif last_close > self.ema_value:
            self.current_bias = BiasDirection.BULLISH
        elif last_close < self.ema_value:
            self.current_bias = BiasDirection.BEARISH
        else:
            self.current_bias = BiasDirection.NEUTRAL
