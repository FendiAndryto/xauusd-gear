"""Calibrated Range Boundary Liquidity Sweep & 3-Layer Mean-Reversion Scalper v2.0 (EXP-03 / TICK-401)."""

from datetime import datetime, timedelta
from typing import Optional, Set

from src.simulator.execution import OrderRequest
from src.simulator.layer_manager import LayerManager
from src.strategies.base import BaseStrategy, TickEvent
from src.strategies.range_detector import RangeDetector, RangeState


class RangeSweepScalperV2(BaseStrategy):
    """Calibrated scalper with HTF Trend Filter, Breakout Cooldown, and deeper liquidity sweeps."""

    def __init__(
        self,
        name: str = "RangeSweepScalperV2",
        lookback_minutes: int = 30,
        min_range_usd: float = 3.0,
        max_range_usd: float = 10.0,
        min_sweep_usd: float = 0.70,        # Increased from 0.45 to filter out minor noise
        max_sweep_usd: float = 2.00,        # Past $2.00 is real runaway trend
        hard_sl_offset_usd: float = 1.20,   # Invalidation buffer beyond sweep extreme
        layer_spacing_usd: float = 0.50,    # Spacing for Layer 2 & 3
        layer_volumes: Optional[list[float]] = None,
        max_spread_usd: float = 0.25,
        cooldown_seconds: float = 1200.0,   # 20-minute cooldown on broken boundary
        allowed_hours_utc: Optional[Set[int]] = None,
    ):
        super().__init__(name)
        self.detector = RangeDetector(
            lookback_minutes=lookback_minutes,
            min_range_usd=min_range_usd,
            max_range_usd=max_range_usd,
        )
        self.layer_mgr = LayerManager(
            layer_volumes=layer_volumes or [0.05, 0.10, 0.15],
            layer_spacing_usd=layer_spacing_usd,
        )
        self.min_sweep_usd = min_sweep_usd
        self.max_sweep_usd = max_sweep_usd
        self.hard_sl_offset = hard_sl_offset_usd
        self.max_spread = max_spread_usd
        self.cooldown_seconds = cooldown_seconds
        self.allowed_hours_utc = allowed_hours_utc if allowed_hours_utc is not None else set(range(0, 21))

        # Sweep tracking state
        self.high_sweep_active = False
        self.high_sweep_peak = 0.0
        self.low_sweep_active = False
        self.low_sweep_trough = 0.0

        # Breakout cooldown timestamps
        self.last_sl_time_high: Optional[datetime] = None
        self.last_sl_time_low: Optional[datetime] = None

    def on_tick(self, tick: TickEvent) -> Optional[OrderRequest]:
        # Update range detector
        range_state: RangeState = self.detector.update(tick.timestamp, tick.bid, tick.ask)
        mid_price = (tick.bid + tick.ask) / 2.0

        # Sync portfolio positions with layer manager
        if self.portfolio and self.layer_mgr.has_active_setup:
            for pid in self.portfolio.open_positions:
                if pid not in self.layer_mgr.current_setup.active_position_ids:
                    self.layer_mgr.register_position(pid)

        # -------------------------------------------------------------
        # 1. Manage Active Layer Setup (SL, TP, Layer 2 & 3 Retests)
        # -------------------------------------------------------------
        if self.layer_mgr.has_active_setup:
            current_side = self.layer_mgr.current_setup.side
            managed_orders = self.layer_mgr.evaluate(tick, self.portfolio)
            if managed_orders:
                # Check if Hard Invalidation SL was triggered -> activate cooldown
                for o in managed_orders:
                    if o.reason == "HARD_INVALIDATION_SL":
                        if current_side == "SELL":
                            self.last_sl_time_high = tick.timestamp
                        else:
                            self.last_sl_time_low = tick.timestamp
                return managed_orders[0]
            return None

        # -------------------------------------------------------------
        # 2. Filter Gating: Session Hour, Spread & Ranging Regime
        # -------------------------------------------------------------
        if tick.timestamp.hour not in self.allowed_hours_utc:
            self._reset_sweep_state()
            return None

        if tick.spread > self.max_spread:
            return None

        if not range_state.is_ranging or range_state.circuit_breaker_active:
            self._reset_sweep_state()
            return None

        r_high = range_state.range_high
        r_low = range_state.range_low
        eq = range_state.equilibrium
        htf_trend = range_state.htf_trend

        # -------------------------------------------------------------
        # 3. BEARISH SWEEP & TRAP AT RANGE HIGH (SELL SETUP)
        # -------------------------------------------------------------
        # Check cooldown on high boundary
        is_high_in_cooldown = (
            self.last_sl_time_high is not None
            and (tick.timestamp - self.last_sl_time_high).total_seconds() < self.cooldown_seconds
        )

        # Rule: Do not sell if boundary in cooldown OR HTF trend is strongly bullish
        if not is_high_in_cooldown and htf_trend != "STRONG_BULLISH":
            if mid_price > r_high:
                penetration = mid_price - r_high
                if self.min_sweep_usd <= penetration <= self.max_sweep_usd:
                    self.high_sweep_active = True
                    self.high_sweep_peak = max(self.high_sweep_peak, mid_price)
                elif penetration > self.max_sweep_usd:
                    # Real runaway breakout to upside -> cancel sweep
                    self.high_sweep_active = False

            elif self.high_sweep_active and mid_price <= r_high:
                # Rejection confirmed! Price crossed back into range
                hard_sl = round(self.high_sweep_peak + self.hard_sl_offset, 3)
                tp1 = eq
                tp2 = round(r_low + 0.35, 3)

                self.high_sweep_active = False
                self.high_sweep_peak = 0.0

                return self.layer_mgr.start_setup(
                    side="SELL",
                    timestamp=tick.timestamp,
                    hard_sl=hard_sl,
                    tp1_price=tp1,
                    tp2_price=tp2,
                )
        else:
            self.high_sweep_active = False

        # -------------------------------------------------------------
        # 4. BULLISH SWEEP & TRAP AT RANGE LOW (BUY SETUP)
        # -------------------------------------------------------------
        # Check cooldown on low boundary
        is_low_in_cooldown = (
            self.last_sl_time_low is not None
            and (tick.timestamp - self.last_sl_time_low).total_seconds() < self.cooldown_seconds
        )

        # Rule: Do not buy if boundary in cooldown OR HTF trend is strongly bearish
        if not is_low_in_cooldown and htf_trend != "STRONG_BEARISH":
            if mid_price < r_low:
                penetration = r_low - mid_price
                if self.min_sweep_usd <= penetration <= self.max_sweep_usd:
                    self.low_sweep_active = True
                    self.low_sweep_trough = min(self.low_sweep_trough or mid_price, mid_price)
                elif penetration > self.max_sweep_usd:
                    # Real runaway breakdown to downside -> cancel sweep
                    self.low_sweep_active = False

            elif self.low_sweep_active and mid_price >= r_low:
                # Rejection confirmed! Price crossed back up into range
                hard_sl = round(self.low_sweep_trough - self.hard_sl_offset, 3)
                tp1 = eq
                tp2 = round(r_high - 0.35, 3)

                self.low_sweep_active = False
                self.low_sweep_trough = 0.0

                return self.layer_mgr.start_setup(
                    side="BUY",
                    timestamp=tick.timestamp,
                    hard_sl=hard_sl,
                    tp1_price=tp1,
                    tp2_price=tp2,
                )
        else:
            self.low_sweep_active = False

        return None

    def _reset_sweep_state(self):
        self.high_sweep_active = False
        self.high_sweep_peak = 0.0
        self.low_sweep_active = False
        self.low_sweep_trough = 0.0
