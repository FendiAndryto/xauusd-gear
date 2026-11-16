"""TICK-SMC-03: M15/M5 Sweep vs Acceptance Classification Engine.

Determines whether price interaction at D1 Boundary (PDH/PDL) is a
Liquidity Sweep (Rejection / Mean Reversion) or Value Acceptance (Breakout Expansion).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from src.strategies.smc.d1_boundary_extractor import D1Boundary


class ReactionType(Enum):
    NONE = "NONE"
    SWEEP_REJECTION_PDH = "SWEEP_REJECTION_PDH"  # Potential SELL
    SWEEP_REJECTION_PDL = "SWEEP_REJECTION_PDL"  # Potential BUY
    SWEEP_REJECTION_ASIA_HIGH = "SWEEP_REJECTION_ASIA_HIGH"  # Potential SELL (Intraday Resistance Sweep)
    SWEEP_REJECTION_ASIA_LOW = "SWEEP_REJECTION_ASIA_LOW"    # Potential BUY (Intraday Support Sweep)
    VALUE_ACCEPTANCE_BULL = "VALUE_ACCEPTANCE_BULL"  # Potential BUY Breakout
    VALUE_ACCEPTANCE_BEAR = "VALUE_ACCEPTANCE_BEAR"  # Potential SELL Breakdown


@dataclass
class M5Bar:
    """Represents a completed 5-minute OHLC bar."""
    start_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def total_range(self) -> float:
        return max(0.01, self.high - self.low)

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def upper_wick_ratio(self) -> float:
        return self.upper_wick / self.total_range

    @property
    def lower_wick_ratio(self) -> float:
        return self.lower_wick / self.total_range

    @property
    def body_ratio(self) -> float:
        return self.body_size / self.total_range


class SweepAcceptanceEngine:
    """Classifies M5/M15 candle reactions at PDH/PDL boundaries."""

    def __init__(
        self,
        min_wick_ratio: float = 0.35,
        min_body_ratio: float = 0.55,
    ):
        self.min_wick_ratio = min_wick_ratio
        self.min_body_ratio = min_body_ratio

    def evaluate_bar(self, bar: M5Bar, boundary: D1Boundary) -> tuple[ReactionType, float]:
        """Evaluate a completed bar against the active D1 boundary.
        
        Returns:
            Tuple of (ReactionType, sweep_extreme_price)
        """
        pdh = boundary.pdh
        pdl = boundary.pdl

        # -------------------------------------------------------------
        # 1. Evaluate Rejection or Acceptance at PDH (Upper Boundary)
        # -------------------------------------------------------------
        if bar.high > pdh:
            # Rejection Sweep: poked above PDH, closed back inside range
            if bar.close <= pdh and bar.upper_wick_ratio >= self.min_wick_ratio:
                return ReactionType.SWEEP_REJECTION_PDH, bar.high
            # True Institutional Acceptance: fresh candle breaking out from inside range to close outside PDH
            elif bar.open <= pdh and bar.close > pdh and bar.body_ratio >= self.min_body_ratio:
                return ReactionType.VALUE_ACCEPTANCE_BULL, bar.high

        # -------------------------------------------------------------
        # 2. Evaluate Rejection or Acceptance at PDL (Lower Boundary)
        # -------------------------------------------------------------
        if bar.low < pdl:
            # Rejection Sweep: poked below PDL, closed back inside range
            if bar.close >= pdl and bar.lower_wick_ratio >= self.min_wick_ratio:
                return ReactionType.SWEEP_REJECTION_PDL, bar.low
            # True Institutional Acceptance: fresh candle breaking down from inside range to close outside PDL
            elif bar.open >= pdl and bar.close < pdl and bar.body_ratio >= self.min_body_ratio:
                return ReactionType.VALUE_ACCEPTANCE_BEAR, bar.low

        # -------------------------------------------------------------
        # 3. Evaluate Asian Session S/R (Active during London/NY: hour >= 7)
        # -------------------------------------------------------------
        if bar.start_time.hour >= 7 and boundary.asia_high is not None and boundary.asia_low is not None:
            if bar.high > boundary.asia_high:
                if bar.close <= boundary.asia_high and bar.upper_wick_ratio >= self.min_wick_ratio:
                    return ReactionType.SWEEP_REJECTION_ASIA_HIGH, bar.high
            if bar.low < boundary.asia_low:
                if bar.close >= boundary.asia_low and bar.lower_wick_ratio >= self.min_wick_ratio:
                    return ReactionType.SWEEP_REJECTION_ASIA_LOW, bar.low

        return ReactionType.NONE, 0.0
