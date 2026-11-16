"""TICK-SMC-01: D1 Boundary & Recursive Mother Bar Extractor Engine.

Extracts Previous Day High (PDH), Previous Day Low (PDL), and Equilibrium (50% Range).
Handles Inside Day / compression by recursively falling back to the parent Mother Bar.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


@dataclass
class DailyBar:
    """Represents a completed or in-progress D1 calendar bar."""
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class D1Boundary:
    """Active daily boundary levels used by the strategy."""
    active_date: date
    pdh: float
    pdl: float
    equilibrium: float
    is_inside_fallback: bool
    mother_bar_date: date
    asia_high: Optional[float] = None
    asia_low: Optional[float] = None

    @property
    def range_usd(self) -> float:
        return self.pdh - self.pdl


class D1BoundaryExtractor:
    """Extracts D1 reference levels with recursive Mother Bar resolution and Asian session tracking."""

    def __init__(self, historical_days: Optional[list[DailyBar]] = None):
        self.history: list[DailyBar] = list(historical_days) if historical_days else []
        self.current_day_bar: Optional[DailyBar] = None
        self.active_boundary: Optional[D1Boundary] = None
        
        # Asian session tracking (00:00 - 07:00 UTC)
        self.running_asia_high: Optional[float] = None
        self.running_asia_low: Optional[float] = None
        self.asia_high: Optional[float] = None
        self.asia_low: Optional[float] = None
        
        # If pre-seeded with at least 1 day, calculate initial boundary
        if self.history:
            self._update_boundary(self.history[-1].bar_date)

    def on_tick(self, timestamp: datetime, bid: float, volume: float = 1.0) -> Optional[D1Boundary]:
        """Update daily bar streaming state on tick arrival and roll day at midnight."""
        tick_date = timestamp.date()
        h = timestamp.hour

        if self.current_day_bar is None:
            self.current_day_bar = DailyBar(
                bar_date=tick_date,
                open=bid,
                high=bid,
                low=bid,
                close=bid,
                volume=volume,
            )
            self.running_asia_high = bid
            self.running_asia_low = bid
            return self.active_boundary

        if tick_date != self.current_day_bar.bar_date:
            # Day rollover (00:00:00 UTC)
            self.history.append(self.current_day_bar)
            self._update_boundary(tick_date)

            # Initialize new day's bar & reset Asian session
            self.current_day_bar = DailyBar(
                bar_date=tick_date,
                open=bid,
                high=bid,
                low=bid,
                close=bid,
                volume=volume,
            )
            self.running_asia_high = bid
            self.running_asia_low = bid
            self.asia_high = None
            self.asia_low = None
        else:
            # Update current day's running bar
            self.current_day_bar.high = max(self.current_day_bar.high, bid)
            self.current_day_bar.low = min(self.current_day_bar.low, bid)
            self.current_day_bar.close = bid
            self.current_day_bar.volume += volume

            # Update Asian session
            if h < 7:
                if self.running_asia_high is None:
                    self.running_asia_high = bid
                    self.running_asia_low = bid
                else:
                    self.running_asia_high = max(self.running_asia_high, bid)
                    self.running_asia_low = min(self.running_asia_low, bid)
            else:
                if self.asia_high is None and self.running_asia_high is not None:
                    self.asia_high = round(self.running_asia_high, 2)
                    self.asia_low = round(self.running_asia_low, 2)

        if self.active_boundary is not None:
            self.active_boundary.asia_high = self.asia_high
            self.active_boundary.asia_low = self.asia_low

        return self.active_boundary

    def seed_daily_bars(self, bars: list[DailyBar]):
        """Seed extractor with historical daily bars."""
        self.history = list(bars)
        if self.history:
            self._update_boundary(self.history[-1].bar_date)

    def _update_boundary(self, for_date: date):
        """Calculate PDH/PDL with recursive mother bar fallback from history."""
        if not self.history:
            return

        # Start with the most recently completed day (D-1)
        idx = len(self.history) - 1
        is_fallback = False

        # Recursive mother bar resolution:
        # If day D-1 is inside D-2, check if D-2 is inside D-3, etc.
        while idx > 0:
            current = self.history[idx]
            prev = self.history[idx - 1]
            
            # An inside bar has strictly lower High and strictly higher Low than its parent
            if current.high <= prev.high and current.low >= prev.low:
                is_fallback = True
                idx -= 1
            else:
                break

        mother_bar = self.history[idx]
        pdh = mother_bar.high
        pdl = mother_bar.low
        eq = round((pdh + pdl) / 2.0, 2)

        self.active_boundary = D1Boundary(
            active_date=for_date,
            pdh=round(pdh, 2),
            pdl=round(pdl, 2),
            equilibrium=eq,
            is_inside_fallback=is_fallback,
            mother_bar_date=mother_bar.bar_date,
        )
