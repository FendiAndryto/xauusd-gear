"""Macro Trend and Daily Regime Detector for XAUUSD (TICK-702 / EXP-08).

Operates on rolling hourly (H1) bars in O(1) time without lookahead bias.
Computes Fast EMA (8 hours) vs Slow EMA (24 hours = 1 day) to classify macro market regimes:
- STRONG_BULLISH: Macro upward momentum. Blocks counter-trend SELLs, allows BUYs on dips.
- STRONG_BEARISH: Macro downward momentum. Blocks counter-trend BUYs, allows SELLs on rallies.
- BALANCED_SIDEWAY: Range-bound / neutral. Allows dual-direction trading.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class MacroRegimeState:
    """Represents current higher-timeframe market regime."""
    regime: str  # "STRONG_BULLISH", "STRONG_BEARISH", "BALANCED_SIDEWAY"
    fast_ema: float
    slow_ema: float
    trend_spread: float
    completed_bars_count: int
    allow_buy: bool
    allow_sell: bool


class MacroTrendDetector:
    """Incrementally aggregates ticks into H1 bars and calculates EMA-8 vs EMA-24."""

    def __init__(
        self,
        fast_hours: int = 8,
        slow_hours: int = 24,
        trend_threshold_usd: float = 2.50,
    ):
        self.fast_hours = fast_hours
        self.slow_hours = slow_hours
        self.trend_threshold_usd = trend_threshold_usd

        # Smoothing factors
        self.alpha_fast = 2.0 / (fast_hours + 1.0)
        self.alpha_slow = 2.0 / (slow_hours + 1.0)

        # EMA state
        self.fast_ema: Optional[float] = None
        self.slow_ema: Optional[float] = None
        self.completed_bars: int = 0

        # Current incomplete hourly bar
        self._current_hour_key: Optional[int] = None
        self._current_bar_high: float = 0.0
        self._current_bar_low: float = 0.0
        self._current_bar_close: float = 0.0

        # Cached state
        self._cached_state: MacroRegimeState = MacroRegimeState(
            regime="BALANCED_SIDEWAY",
            fast_ema=0.0,
            slow_ema=0.0,
            trend_spread=0.0,
            completed_bars_count=0,
            allow_buy=True,
            allow_sell=True,
        )

    def update(self, timestamp: datetime, bid: float, ask: float) -> MacroRegimeState:
        """Process incoming tick and update H1 bar / EMAs if an hour turned over."""
        mid = (bid + ask) / 2.0
        ts_epoch = timestamp.timestamp()
        hour_key = int(ts_epoch // 3600)

        if self._current_hour_key is None:
            # First tick ever received
            self._current_hour_key = hour_key
            self._current_bar_high = mid
            self._current_bar_low = mid
            self._current_bar_close = mid
            return self._cached_state

        if hour_key == self._current_hour_key:
            # Still in current hour
            if mid > self._current_bar_high:
                self._current_bar_high = mid
            elif mid < self._current_bar_low:
                self._current_bar_low = mid
            self._current_bar_close = mid
            return self._cached_state

        # Hour turned over! Push completed bar
        # Typical price of completed bar: (High + Low + Close) / 3
        bar_typical = (self._current_bar_high + self._current_bar_low + self._current_bar_close) / 3.0

        if self.fast_ema is None:
            self.fast_ema = bar_typical
            self.slow_ema = bar_typical
        else:
            self.fast_ema = self.alpha_fast * bar_typical + (1.0 - self.alpha_fast) * self.fast_ema
            self.slow_ema = self.alpha_slow * bar_typical + (1.0 - self.alpha_slow) * self.slow_ema

        self.completed_bars += 1

        # Classify regime
        trend_spread = round(self.fast_ema - self.slow_ema, 3)

        # Require at least 5 completed hours before enforcing strong regime biases
        if self.completed_bars >= 5:
            if trend_spread >= self.trend_threshold_usd:
                regime = "STRONG_BULLISH"
                allow_buy = True
                allow_sell = False  # Block counter-trend shorting
            elif trend_spread <= -self.trend_threshold_usd:
                regime = "STRONG_BEARISH"
                allow_buy = False  # Block catching falling knives
                allow_sell = True
            else:
                regime = "BALANCED_SIDEWAY"
                allow_buy = True
                allow_sell = True
        else:
            regime = "BALANCED_SIDEWAY"
            allow_buy = True
            allow_sell = True

        self._cached_state = MacroRegimeState(
            regime=regime,
            fast_ema=round(self.fast_ema, 3),
            slow_ema=round(self.slow_ema, 3),
            trend_spread=trend_spread,
            completed_bars_count=self.completed_bars,
            allow_buy=allow_buy,
            allow_sell=allow_sell,
        )

        # Reset current bar for new hour
        self._current_hour_key = hour_key
        self._current_bar_high = mid
        self._current_bar_low = mid
        self._current_bar_close = mid

        return self._cached_state

    def reset(self):
        """Reset internal state."""
        self.fast_ema = None
        self.slow_ema = None
        self.completed_bars = 0
        self._current_hour_key = None
        self._current_bar_high = 0.0
        self._current_bar_low = 0.0
        self._current_bar_close = 0.0
        self._cached_state = MacroRegimeState(
            regime="BALANCED_SIDEWAY",
            fast_ema=0.0,
            slow_ema=0.0,
            trend_spread=0.0,
            completed_bars_count=0,
            allow_buy=True,
            allow_sell=True,
        )
