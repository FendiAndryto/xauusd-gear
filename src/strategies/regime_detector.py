"""Market Regime Detector and Trend/Range Switchboard for XAUUSD (TICK-1102 / EXP-12).

Classifies market state into:
- RANGE_BOUND: Low-to-moderate volatility, balanced price action. Ideal for Engine A (Mean-Reversion).
- STRONG_BULLISH_TREND: Aggressive upward momentum / expansion. Handed over to Engine B (Long Breakout).
- STRONG_BEARISH_TREND: Aggressive downward momentum / expansion. Handed over to Engine B (Short Breakout).
- UNCERTAIN / TRANSITION: Ambiguous regime, entries held.

Supports 3 pluggable operational modes:
1. "ORB": Opening Range Breakout (London Session 07:00-08:00 UTC anchor).
2. "DYNAMIC_EXPANSION": Daily Range Expansion relative to day open price ($15.00 threshold).
3. "EMA_SLOPE": Macro H1 EMA-8 vs EMA-24 slope & momentum velocity.
4. "ENSEMBLE": Combines multiple indicators (e.g. Dynamic Expansion OR strong EMA slope).

Operates in O(1) tick streaming time with zero future lookahead bias.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class MarketRegimeState:
    """Represents current real-time market regime."""
    regime: str                # "RANGE_BOUND", "STRONG_BULLISH_TREND", "STRONG_BEARISH_TREND", "UNCERTAIN"
    mode: str                  # Active evaluation mode
    is_trending: bool          # True if either bullish or bearish trend
    trend_direction: str       # "BULLISH", "BEARISH", "NONE"
    day_open_price: float      # Day's initial opening price at 00:00 UTC
    day_expansion_usd: float   # Current displacement from day open price
    orb_high: float            # Opening Range High
    orb_low: float             # Opening Range Low
    orb_active: bool           # True if ORB window completed and armed
    ema_spread: float          # H1 Fast EMA - Slow EMA spread
    ema_slope: float           # Hourly slope of Fast EMA
    trend_latched: bool = False       # True if breakout occurred and trend is latched
    latched_direction: str = "NONE"   # "BULLISH", "BEARISH", "NONE"


class MarketRegimeDetector:
    """Streaming tick-by-tick market regime classifier."""

    def __init__(
        self,
        mode: str = "DYNAMIC_EXPANSION",
        daily_expansion_threshold_usd: float = 15.00,
        orb_start_hour_utc: int = 7,
        orb_duration_hours: int = 1,
        orb_threshold_usd: float = 3.00,
        ema_fast_hours: int = 8,
        ema_slow_hours: int = 24,
        ema_trend_threshold_usd: float = 2.50,
        ema_slope_threshold_usd: float = 0.15,
        enable_trend_latch: bool = False,
    ):
        self.mode = mode.upper()
        self.daily_expansion_threshold_usd = daily_expansion_threshold_usd
        self.orb_start_hour_utc = orb_start_hour_utc
        self.orb_duration_hours = orb_duration_hours
        self.orb_threshold_usd = orb_threshold_usd
        self.ema_trend_threshold_usd = ema_trend_threshold_usd
        self.ema_slope_threshold_usd = ema_slope_threshold_usd
        self.enable_trend_latch = enable_trend_latch

        # Smoothing factors for EMA
        self.alpha_fast = 2.0 / (ema_fast_hours + 1.0)
        self.alpha_slow = 2.0 / (ema_slow_hours + 1.0)

        # State tracking: Calendar Day
        self._current_day_str: Optional[str] = None
        self._day_open_price: float = 0.0
        self._day_high: float = 0.0
        self._day_low: float = 0.0

        # State tracking: ORB
        self._orb_window_active: bool = False
        self._orb_armed: bool = False
        self._orb_high: float = 0.0
        self._orb_low: float = 0.0
        self._trend_latched: bool = False
        self._latched_direction: str = "NONE"

        # State tracking: Macro H1 EMA
        self._current_hour_key: Optional[int] = None
        self._bar_h: float = 0.0
        self._bar_l: float = 0.0
        self._bar_c: float = 0.0
        self._fast_ema: Optional[float] = None
        self._slow_ema: Optional[float] = None
        self._prev_fast_ema: Optional[float] = None
        self._completed_hours: int = 0
        self._ema_slope: float = 0.0

        # Cached state
        self._cached_state: MarketRegimeState = MarketRegimeState(
            regime="RANGE_BOUND",
            mode=self.mode,
            is_trending=False,
            trend_direction="NONE",
            day_open_price=0.0,
            day_expansion_usd=0.0,
            orb_high=0.0,
            orb_low=0.0,
            orb_active=False,
            ema_spread=0.0,
            ema_slope=0.0,
        )

    def update(self, timestamp: datetime, bid: float, ask: float) -> MarketRegimeState:
        """Process incoming tick and update regime state in O(1) time."""
        mid = (bid + ask) / 2.0
        day_str = timestamp.strftime("%Y-%m-%d")

        # -------------------------------------------------------------
        # 1. Day Rollover Tracking (00:00 UTC)
        # -------------------------------------------------------------
        if self._current_day_str != day_str:
            self._current_day_str = day_str
            self._day_open_price = mid
            self._day_high = mid
            self._day_low = mid
            # Reset daily ORB state
            self._orb_window_active = False
            self._orb_armed = False
            self._orb_high = 0.0
            self._orb_low = 0.0
            self._trend_latched = False
            self._latched_direction = "NONE"
        else:
            if mid > self._day_high:
                self._day_high = mid
            elif mid < self._day_low:
                self._day_low = mid

        day_expansion = round(mid - self._day_open_price, 3)

        # -------------------------------------------------------------
        # 2. Hourly Bar & EMA Tracking
        # -------------------------------------------------------------
        hour_key = int(timestamp.timestamp() // 3600)
        if self._current_hour_key is None:
            self._current_hour_key = hour_key
            self._bar_h = mid
            self._bar_l = mid
            self._bar_c = mid
        elif hour_key == self._current_hour_key:
            if mid > self._bar_h:
                self._bar_h = mid
            elif mid < self._bar_l:
                self._bar_l = mid
            self._bar_c = mid
        else:
            # Hour completed! Update EMAs
            typical = (self._bar_h + self._bar_l + self._bar_c) / 3.0
            if self._fast_ema is None:
                self._fast_ema = typical
                self._slow_ema = typical
                self._prev_fast_ema = typical
            else:
                self._prev_fast_ema = self._fast_ema
                self._fast_ema = self.alpha_fast * typical + (1.0 - self.alpha_fast) * self._fast_ema
                self._slow_ema = self.alpha_slow * typical + (1.0 - self.alpha_slow) * self._slow_ema
                self._ema_slope = round(self._fast_ema - self._prev_fast_ema, 4)

            self._completed_hours += 1
            self._current_hour_key = hour_key
            self._bar_h = mid
            self._bar_l = mid
            self._bar_c = mid

        ema_spread = round(self._fast_ema - self._slow_ema, 3) if (self._fast_ema and self._slow_ema) else 0.0

        # -------------------------------------------------------------
        # 3. Opening Range Breakout (ORB) Window Tracking
        # -------------------------------------------------------------
        h_utc = timestamp.hour
        orb_end_hour = self.orb_start_hour_utc + self.orb_duration_hours

        if self.orb_start_hour_utc <= h_utc < orb_end_hour:
            # Accumulating ORB range
            if not self._orb_window_active:
                self._orb_window_active = True
                self._orb_high = mid
                self._orb_low = mid
            else:
                if mid > self._orb_high:
                    self._orb_high = mid
                elif mid < self._orb_low:
                    self._orb_low = mid
        elif h_utc >= orb_end_hour and self._orb_window_active:
            # ORB window completed, arm the trigger
            self._orb_armed = True

        # -------------------------------------------------------------
        # 4. Regime Decision Engine (Option-Based)
        # -------------------------------------------------------------
        regime = "RANGE_BOUND"
        trend_direction = "NONE"
        is_trending = False

        if self.mode == "DYNAMIC_EXPANSION":
            if day_expansion >= self.daily_expansion_threshold_usd:
                regime = "STRONG_BULLISH_TREND"
                trend_direction = "BULLISH"
                is_trending = True
            elif day_expansion <= -self.daily_expansion_threshold_usd:
                regime = "STRONG_BEARISH_TREND"
                trend_direction = "BEARISH"
                is_trending = True
            else:
                regime = "RANGE_BOUND"
                trend_direction = "NONE"
                is_trending = False

        elif self.mode == "ORB":
            if self._orb_armed and (self._orb_high > self._orb_low):
                if mid >= self._orb_high + self.orb_threshold_usd:
                    regime = "STRONG_BULLISH_TREND"
                    trend_direction = "BULLISH"
                    is_trending = True
                    if self.enable_trend_latch:
                        self._trend_latched = True
                        self._latched_direction = "BULLISH"
                elif mid <= self._orb_low - self.orb_threshold_usd:
                    regime = "STRONG_BEARISH_TREND"
                    trend_direction = "BEARISH"
                    is_trending = True
                    if self.enable_trend_latch:
                        self._trend_latched = True
                        self._latched_direction = "BEARISH"
                elif self.enable_trend_latch and self._trend_latched:
                    # Invalidation check:
                    if self._latched_direction == "BULLISH":
                        if mid < self._orb_low:
                            # Invalidation: price penetrated completely through opposite side
                            self._trend_latched = False
                            self._latched_direction = "NONE"
                            regime = "RANGE_BOUND"
                            trend_direction = "NONE"
                            is_trending = False
                        else:
                            regime = "STRONG_BULLISH_TREND"
                            trend_direction = "BULLISH"
                            is_trending = True
                    elif self._latched_direction == "BEARISH":
                        if mid > self._orb_high:
                            # Invalidation: price penetrated completely through opposite side
                            self._trend_latched = False
                            self._latched_direction = "NONE"
                            regime = "RANGE_BOUND"
                            trend_direction = "NONE"
                            is_trending = False
                        else:
                            regime = "STRONG_BEARISH_TREND"
                            trend_direction = "BEARISH"
                            is_trending = True
                else:
                    regime = "RANGE_BOUND"
                    trend_direction = "NONE"
                    is_trending = False
            else:
                # Before or during ORB, treat as normal range
                regime = "RANGE_BOUND"
                trend_direction = "NONE"
                is_trending = False

        elif self.mode == "EMA_SLOPE":
            if self._completed_hours >= 5:
                if (ema_spread >= self.ema_trend_threshold_usd and 
                    self._ema_slope >= self.ema_slope_threshold_usd):
                    regime = "STRONG_BULLISH_TREND"
                    trend_direction = "BULLISH"
                    is_trending = True
                elif (ema_spread <= -self.ema_trend_threshold_usd and 
                      self._ema_slope <= -self.ema_slope_threshold_usd):
                    regime = "STRONG_BEARISH_TREND"
                    trend_direction = "BEARISH"
                    is_trending = True
                else:
                    regime = "RANGE_BOUND"
                    trend_direction = "NONE"
                    is_trending = False
            else:
                regime = "RANGE_BOUND"
                trend_direction = "NONE"
                is_trending = False

        elif self.mode == "ENSEMBLE":
            # Multi-condition ensemble: trigger if Daily Expansion OR (ORB armed and broken)
            is_exp_bull = day_expansion >= self.daily_expansion_threshold_usd
            is_exp_bear = day_expansion <= -self.daily_expansion_threshold_usd
            is_orb_bull = self._orb_armed and mid >= (self._orb_high + self.orb_threshold_usd)
            is_orb_bear = self._orb_armed and mid <= (self._orb_low - self.orb_threshold_usd)

            if is_exp_bull or is_orb_bull:
                regime = "STRONG_BULLISH_TREND"
                trend_direction = "BULLISH"
                is_trending = True
            elif is_exp_bear or is_orb_bear:
                regime = "STRONG_BEARISH_TREND"
                trend_direction = "BEARISH"
                is_trending = True
            else:
                regime = "RANGE_BOUND"
                trend_direction = "NONE"
                is_trending = False

        self._cached_state = MarketRegimeState(
            regime=regime,
            mode=self.mode,
            is_trending=is_trending,
            trend_direction=trend_direction,
            day_open_price=round(self._day_open_price, 3),
            day_expansion_usd=day_expansion,
            orb_high=round(self._orb_high, 3),
            orb_low=round(self._orb_low, 3),
            orb_active=self._orb_armed,
            ema_spread=ema_spread,
            ema_slope=self._ema_slope,
            trend_latched=self._trend_latched,
            latched_direction=self._latched_direction,
        )

        return self._cached_state

    def reset(self):
        """Reset internal detector state."""
        self._current_day_str = None
        self._day_open_price = 0.0
        self._day_high = 0.0
        self._day_low = 0.0
        self._orb_window_active = False
        self._orb_armed = False
        self._orb_high = 0.0
        self._orb_low = 0.0
        self._trend_latched = False
        self._latched_direction = "NONE"
        self._current_hour_key = None
        self._fast_ema = None
        self._slow_ema = None
        self._prev_fast_ema = None
        self._completed_hours = 0
        self._ema_slope = 0.0
