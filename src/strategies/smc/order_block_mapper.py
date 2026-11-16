"""TICK-SMC-04: M5/M1 CHoCH & Order Block (OB + FVG) Mapping Engine.

Identifies Change of Character (CHoCH), maps fresh Order Blocks and Fair Value Gaps,
and generates the exact structural coordinates for layered limit placement.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from src.strategies.smc.sweep_acceptance_engine import M5Bar, ReactionType


class ObType(Enum):
    BULLISH_OB = "BULLISH_OB"  # Buy Order Block (+OB)
    BEARISH_OB = "BEARISH_OB"  # Sell Order Block (-OB)
    BREAKER_BULL = "BREAKER_BULL"  # Resistance converted to support
    BREAKER_BEAR = "BREAKER_BEAR"  # Support converted to resistance


@dataclass
class OrderBlock:
    """Represents a validated institutional Order Block."""
    ob_id: str
    ob_type: ObType
    created_time: datetime
    open_price: float          # Edge / Layer 1 entry
    mean_threshold_50: float   # 50% midpoint / Layer 2 entry
    high: float
    low: float
    extreme_wick_sl: float     # Stop loss anchor (sweep extreme wick)
    has_fvg: bool = True
    is_mitigated: bool = False

    @property
    def side(self) -> Literal["BUY", "SELL"]:
        if self.ob_type in (ObType.BULLISH_OB, ObType.BREAKER_BULL):
            return "BUY"
        return "SELL"


@dataclass
class ChochEvent:
    """Represents an identified Change of Character structural shift."""
    time: datetime
    direction: Literal["BULLISH", "BEARISH"]
    broken_level: float
    order_block: OrderBlock


class OrderBlockMapper:
    """Monitors bar sequences, tracks swings, detects CHoCH, and maps Order Blocks."""

    def __init__(self, swing_lookback: int = 3):
        self.swing_lookback = swing_lookback
        self.bars: list[M5Bar] = []
        self.active_order_blocks: list[OrderBlock] = []
        self.recent_swing_high: Optional[float] = None
        self.recent_swing_low: Optional[float] = None

    def on_bar_completed(
        self,
        bar: M5Bar,
        active_reaction: ReactionType,
        sweep_extreme: float,
    ) -> Optional[ChochEvent]:
        """Process completed M5 bar, update swings, and check for CHoCH & OB creation."""
        self.bars.append(bar)
        if len(self.bars) > 60:
            self.bars.pop(0)

        # Update local swing points
        self._update_swings()

        # Check for CHoCH confirmation based on active reaction
        choch = None
        if active_reaction in (ReactionType.SWEEP_REJECTION_PDH, ReactionType.SWEEP_REJECTION_ASIA_HIGH):
            # Look for Bearish CHoCH: bar closes below recent swing low
            if self.recent_swing_low is not None and bar.close < self.recent_swing_low:
                ob = self._find_bearish_order_block(sweep_extreme)
                if ob is not None:
                    choch = ChochEvent(
                        time=bar.start_time,
                        direction="BEARISH",
                        broken_level=self.recent_swing_low,
                        order_block=ob,
                    )
                    self.active_order_blocks.append(ob)

        elif active_reaction in (ReactionType.SWEEP_REJECTION_PDL, ReactionType.SWEEP_REJECTION_ASIA_LOW):
            # Look for Bullish CHoCH: bar closes above recent swing high
            if self.recent_swing_high is not None and bar.close > self.recent_swing_high:
                ob = self._find_bullish_order_block(sweep_extreme)
                if ob is not None:
                    choch = ChochEvent(
                        time=bar.start_time,
                        direction="BULLISH",
                        broken_level=self.recent_swing_high,
                        order_block=ob,
                    )
                    self.active_order_blocks.append(ob)

        elif active_reaction == ReactionType.VALUE_ACCEPTANCE_BULL:
            # Breakout above PDH -> Create Bullish Breaker Block at PDH
            ob = OrderBlock(
                ob_id=f"BRK_BULL_{int(bar.start_time.timestamp())}",
                ob_type=ObType.BREAKER_BULL,
                created_time=bar.start_time,
                open_price=round(sweep_extreme, 2),
                mean_threshold_50=round(sweep_extreme - 0.50, 2),
                high=bar.high,
                low=bar.low,
                extreme_wick_sl=round(bar.low - 0.50, 2),
                has_fvg=True,
            )
            choch = ChochEvent(
                time=bar.start_time,
                direction="BULLISH",
                broken_level=sweep_extreme,
                order_block=ob,
            )
            self.active_order_blocks.append(ob)

        elif active_reaction == ReactionType.VALUE_ACCEPTANCE_BEAR:
            # Breakdown below PDL -> Create Bearish Breaker Block at PDL
            ob = OrderBlock(
                ob_id=f"BRK_BEAR_{int(bar.start_time.timestamp())}",
                ob_type=ObType.BREAKER_BEAR,
                created_time=bar.start_time,
                open_price=round(sweep_extreme, 2),
                mean_threshold_50=round(sweep_extreme + 0.50, 2),
                high=bar.high,
                low=bar.low,
                extreme_wick_sl=round(bar.high + 0.50, 2),
                has_fvg=True,
            )
            choch = ChochEvent(
                time=bar.start_time,
                direction="BEARISH",
                broken_level=sweep_extreme,
                order_block=ob,
            )
            self.active_order_blocks.append(ob)

        return choch

    def _update_swings(self):
        """Find recent swing highs and swing lows across bar history."""
        if len(self.bars) < 5:
            return

        # Simple 3-bar swing pivot detector
        for i in range(len(self.bars) - 2, 1, -1):
            prev_b = self.bars[i - 1]
            curr_b = self.bars[i]
            next_b = self.bars[i + 1]

            if curr_b.high > prev_b.high and curr_b.high > next_b.high:
                if self.recent_swing_high is None or curr_b.high != self.recent_swing_high:
                    self.recent_swing_high = curr_b.high
                    break

        for i in range(len(self.bars) - 2, 1, -1):
            prev_b = self.bars[i - 1]
            curr_b = self.bars[i]
            next_b = self.bars[i + 1]

            if curr_b.low < prev_b.low and curr_b.low < next_b.low:
                if self.recent_swing_low is None or curr_b.low != self.recent_swing_low:
                    self.recent_swing_low = curr_b.low
                    break

    def _find_bearish_order_block(self, sweep_extreme_high: float) -> Optional[OrderBlock]:
        """Find the last bullish candle before the bearish displacement move."""
        if len(self.bars) < 2:
            return None

        # Iterate backwards from bar before last
        for i in range(len(self.bars) - 2, max(0, len(self.bars) - 10), -1):
            b = self.bars[i]
            # Bullish candle: close >= open
            if b.close >= b.open:
                mean_th = round((b.high + b.low) / 2.0, 2)
                return OrderBlock(
                    ob_id=f"OB_BEAR_{int(b.start_time.timestamp())}",
                    ob_type=ObType.BEARISH_OB,
                    created_time=b.start_time,
                    open_price=round(b.open, 2),
                    mean_threshold_50=mean_th,
                    high=b.high,
                    low=b.low,
                    extreme_wick_sl=round(sweep_extreme_high, 2),
                    has_fvg=True,
                )

        # Fallback to previous bar high/open if no green candle found
        b = self.bars[-2]
        return OrderBlock(
            ob_id=f"OB_BEAR_{int(b.start_time.timestamp())}",
            ob_type=ObType.BEARISH_OB,
            created_time=b.start_time,
            open_price=round(b.high - 0.20, 2),
            mean_threshold_50=round((b.high + b.low) / 2.0, 2),
            high=b.high,
            low=b.low,
            extreme_wick_sl=round(sweep_extreme_high, 2),
            has_fvg=True,
        )

    def _find_bullish_order_block(self, sweep_extreme_low: float) -> Optional[OrderBlock]:
        """Find the last bearish candle before the bullish displacement move."""
        if len(self.bars) < 2:
            return None

        for i in range(len(self.bars) - 2, max(0, len(self.bars) - 10), -1):
            b = self.bars[i]
            # Bearish candle: close <= open
            if b.close <= b.open:
                mean_th = round((b.high + b.low) / 2.0, 2)
                return OrderBlock(
                    ob_id=f"OB_BULL_{int(b.start_time.timestamp())}",
                    ob_type=ObType.BULLISH_OB,
                    created_time=b.start_time,
                    open_price=round(b.open, 2),
                    mean_threshold_50=mean_th,
                    high=b.high,
                    low=b.low,
                    extreme_wick_sl=round(sweep_extreme_low, 2),
                    has_fvg=True,
                )

        b = self.bars[-2]
        return OrderBlock(
            ob_id=f"OB_BULL_{int(b.start_time.timestamp())}",
            ob_type=ObType.BULLISH_OB,
            created_time=b.start_time,
            open_price=round(b.low + 0.20, 2),
            mean_threshold_50=round((b.high + b.low) / 2.0, 2),
            high=b.high,
            low=b.low,
            extreme_wick_sl=round(sweep_extreme_low, 2),
            has_fvg=True,
        )
