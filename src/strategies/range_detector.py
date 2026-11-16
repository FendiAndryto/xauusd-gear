"""High-Performance Range Boundary and Market Regime Detector with HTF Trend Filter (TICK-301/TICK-401)."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class RangeState:
    """Current state of market range boundaries, regime, and higher-timeframe trend."""
    is_ranging: bool
    range_high: float
    range_low: float
    equilibrium: float
    range_width: float
    circuit_breaker_active: bool
    recent_velocity: float
    htf_trend: str  # "NEUTRAL", "STRONG_BULLISH", "STRONG_BEARISH"


class RangeDetector:
    """Maintains rolling completed 1-minute bars to compute stable range boundaries and HTF trend in O(1) time."""

    def __init__(
        self,
        lookback_minutes: int = 30,          # 30-minute consolidation window
        min_range_usd: float = 3.0,          # Minimum $3.00 range width
        max_range_usd: float = 10.0,         # Maximum $10.00 range width
        max_tick_velocity: float = 30.0,     # Max ticks/sec threshold (circuit breaker)
        htf_trend_threshold_usd: float = 1.20, # Minimum MA difference for strong trend
    ):
        self.lookback_minutes = lookback_minutes
        self.min_range_usd = min_range_usd
        self.max_range_usd = max_range_usd
        self.max_tick_velocity = max_tick_velocity
        self.htf_trend_threshold = htf_trend_threshold_usd

        # Completed bars: deque of (minute_key, high, low) - buffer up to 180 bars (3 hours)
        self.bars: deque[tuple[int, float, float]] = deque(maxlen=max(180, lookback_minutes * 2))
        
        # Current active bar
        self._current_minute_key: Optional[int] = None
        self._current_bar_high: float = 0.0
        self._current_bar_low: float = 0.0

        # Velocity tracker (last 3 seconds)
        self._recent_ticks: deque[float] = deque()

        # Cached range values
        self._cached_state: Optional[RangeState] = None

    def update(self, timestamp: datetime, bid: float, ask: float) -> RangeState:
        """Update detector with latest arriving tick."""
        mid = (bid + ask) / 2.0
        ts_epoch = timestamp.timestamp()

        # 1. Update Velocity Tracker (rolling 3.0 seconds)
        self._recent_ticks.append(ts_epoch)
        cutoff_velocity = ts_epoch - 3.0
        while self._recent_ticks and self._recent_ticks[0] < cutoff_velocity:
            self._recent_ticks.popleft()

        velocity_dt = max(0.5, ts_epoch - self._recent_ticks[0]) if len(self._recent_ticks) > 1 else 1.0
        current_velocity = len(self._recent_ticks) / velocity_dt
        circuit_breaker = current_velocity > self.max_tick_velocity

        # 2. Minute Bar Aggregation
        minute_key = int(ts_epoch // 60)

        if self._current_minute_key is None:
            self._current_minute_key = minute_key
            self._current_bar_high = mid
            self._current_bar_low = mid
        elif minute_key == self._current_minute_key:
            if mid > self._current_bar_high:
                self._current_bar_high = mid
            elif mid < self._current_bar_low:
                self._current_bar_low = mid
        else:
            # Minute turned over! Push completed bar
            self.bars.append((self._current_minute_key, self._current_bar_high, self._current_bar_low))
            self._current_minute_key = minute_key
            self._current_bar_high = mid
            self._current_bar_low = mid

            # Recalculate stable range boundaries & HTF trend
            if len(self.bars) >= 5:
                # Use only the last lookback_minutes bars for range boundaries
                recent_bars = list(self.bars)[-self.lookback_minutes:]
                highs = [b[1] for b in recent_bars]
                lows = [b[2] for b in recent_bars]
                r_high = round(max(highs), 3)
                r_low = round(min(lows), 3)
                width = round(r_high - r_low, 3)
                eq = round((r_high + r_low) / 2.0, 3)
                is_ranging = (self.min_range_usd <= width <= self.max_range_usd)

                # Compute HTF Trend using Fast MA (last 8 bars) vs Slow MA (last 25 bars)
                htf_trend = "NEUTRAL"
                if len(recent_bars) >= 15:
                    fast_count = min(8, len(recent_bars))
                    slow_count = min(25, len(recent_bars))
                    fast_ma = sum((b[1] + b[2]) / 2.0 for b in recent_bars[-fast_count:]) / fast_count
                    slow_ma = sum((b[1] + b[2]) / 2.0 for b in recent_bars[-slow_count:]) / slow_count
                    ma_diff = fast_ma - slow_ma

                    if ma_diff >= self.htf_trend_threshold:
                        htf_trend = "STRONG_BULLISH"
                    elif ma_diff <= -self.htf_trend_threshold:
                        htf_trend = "STRONG_BEARISH"

                self._cached_state = RangeState(
                    is_ranging=is_ranging,
                    range_high=r_high,
                    range_low=r_low,
                    equilibrium=eq,
                    range_width=width,
                    circuit_breaker_active=False,
                    recent_velocity=current_velocity,
                    htf_trend=htf_trend,
                )

        # Return cached state or default
        if self._cached_state is not None:
            return RangeState(
                is_ranging=self._cached_state.is_ranging and (not circuit_breaker),
                range_high=self._cached_state.range_high,
                range_low=self._cached_state.range_low,
                equilibrium=self._cached_state.equilibrium,
                range_width=self._cached_state.range_width,
                circuit_breaker_active=circuit_breaker,
                recent_velocity=current_velocity,
                htf_trend=self._cached_state.htf_trend,
            )

        return RangeState(
            is_ranging=False,
            range_high=mid,
            range_low=mid,
            equilibrium=mid,
            range_width=0.0,
            circuit_breaker_active=circuit_breaker,
            recent_velocity=current_velocity,
            htf_trend="NEUTRAL",
        )
