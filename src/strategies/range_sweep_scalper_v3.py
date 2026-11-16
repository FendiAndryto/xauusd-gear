"""Adaptive Range Boundary Sweep & Session-Aware Scalper v3.0 (EXP-04 / TICK-404).

Incorporates:
1. Dynamic Session Regime (Rollover Blackout, Asian 50% lot/max 2 layers, Prime 100% lot/max 3 layers).
2. Adaptive Range Width Sweet Spot ($5.00 to $12.00).
3. Configurable Breakeven Policy: NONE, STRICT, BUFFER, STEP_LOCK.
4. HTF Trend Filter & Broken Boundary Cooldown.
"""

from datetime import datetime
from typing import Optional, Set

from src.simulator.execution import OrderRequest
from src.simulator.layer_manager import LayerManager, BEPolicy
from src.strategies.base import BaseStrategy, TickEvent
from src.strategies.range_detector import RangeDetector, RangeState
from src.strategies.session_manager import SessionRegimeManager, SessionRegime


class RangeSweepScalperV3(BaseStrategy):
    """Session-Aware Scalper with Empirical BE Matrix and Range Sweet Spot."""

    def __init__(
        self,
        name: str = "RangeSweepScalperV3",
        lookback_minutes: int = 30,
        min_range_usd: float = 5.0,          # Sweet spot: $5.00 minimum
        max_range_usd: float = 12.0,         # Sweet spot: $12.00 maximum
        min_sweep_usd: float = 0.70,         # Liquidity sweep depth threshold
        max_sweep_usd: float = 2.00,         # Cutoff for runaway momentum
        hard_sl_offset_usd: float = 1.20,    # Invalidation buffer
        layer_spacing_usd: float = 0.50,     # Retest spacing for Layer 2 & 3
        layer_volumes: Optional[list[float]] = None,
        max_spread_usd: float = 0.25,        # Normal spread tolerance
        cooldown_seconds: float = 1200.0,    # 20-minute cooldown
        be_policy: str = "NONE",             # "NONE", "STRICT", "BUFFER", "STEP_LOCK"
    ):
        super().__init__(name)
        self.detector = RangeDetector(
            lookback_minutes=lookback_minutes,
            min_range_usd=min_range_usd,
            max_range_usd=max_range_usd,
        )
        self.session_mgr = SessionRegimeManager()
        self.layer_mgr = LayerManager(
            layer_volumes=layer_volumes or [0.05, 0.10, 0.15],
            layer_spacing_usd=layer_spacing_usd,
            be_policy=be_policy,
        )
        self.min_sweep_usd = min_sweep_usd
        self.max_sweep_usd = max_sweep_usd
        self.hard_sl_offset = hard_sl_offset_usd
        self.max_spread = max_spread_usd
        self.cooldown_seconds = cooldown_seconds
        self.be_policy = be_policy

        # Sweep tracking state
        self.high_sweep_active = False
        self.high_sweep_peak = 0.0
        self.low_sweep_active = False
        self.low_sweep_trough = 0.0

        # Boundary cooldown timestamps
        self.last_sl_time_high: Optional[datetime] = None
        self.last_sl_time_low: Optional[datetime] = None

    def on_tick(self, tick: TickEvent) -> Optional[OrderRequest]:
        # Update range detector
        range_state: RangeState = self.detector.update(tick.timestamp, tick.bid, tick.ask)
        mid_price = (tick.bid + tick.ask) / 2.0

        # Sync open portfolio positions to layer manager
        if self.portfolio and self.layer_mgr.has_active_setup:
            for pid in self.portfolio.open_positions:
                if pid not in self.layer_mgr.current_setup.active_position_ids:
                    self.layer_mgr.register_position(pid)

        # -------------------------------------------------------------
        # 1. Manage Active Layer Setup (SL, TP, Breakeven, Retest Layers)
        # -------------------------------------------------------------
        if self.layer_mgr.has_active_setup:
            current_side = self.layer_mgr.current_setup.side
            managed_orders = self.layer_mgr.evaluate(tick, self.portfolio)
            if managed_orders:
                for o in managed_orders:
                    if o.reason in ("HARD_INVALIDATION_SL", "BE_OR_BUFFER_SL"):
                        if current_side == "SELL":
                            self.last_sl_time_high = tick.timestamp
                        else:
                            self.last_sl_time_low = tick.timestamp
                return managed_orders[0]
            return None

        # -------------------------------------------------------------
        # 2. Session Regime, Spread & Range Sweet Spot Gating
        # -------------------------------------------------------------
        regime: SessionRegime = self.session_mgr.get_regime(tick.timestamp)

        # Disallow new entries during rollover blackout (21:00 - 22:59 UTC)
        if not regime.allow_new_entries:
            self._reset_sweep_state()
            return None

        # Filter abnormal spread spikes
        if tick.spread > self.max_spread:
            return None

        # Range must be active and not under news circuit breaker
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
        is_high_in_cooldown = (
            self.last_sl_time_high is not None
            and (tick.timestamp - self.last_sl_time_high).total_seconds() < self.cooldown_seconds
        )

        if not is_high_in_cooldown and htf_trend != "STRONG_BULLISH":
            if mid_price > r_high:
                penetration = mid_price - r_high
                if self.min_sweep_usd <= penetration <= self.max_sweep_usd:
                    self.high_sweep_active = True
                    self.high_sweep_peak = max(self.high_sweep_peak, mid_price)
                elif penetration > self.max_sweep_usd:
                    self.high_sweep_active = False

            elif self.high_sweep_active and mid_price <= r_high:
                # Rejection confirmed! Price crossed back down into range
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
                    boundary_price=r_high,
                    lot_multiplier=regime.lot_multiplier,
                    max_layers=regime.max_layers,
                )
        else:
            self.high_sweep_active = False

        # -------------------------------------------------------------
        # 4. BULLISH SWEEP & TRAP AT RANGE LOW (BUY SETUP)
        # -------------------------------------------------------------
        is_low_in_cooldown = (
            self.last_sl_time_low is not None
            and (tick.timestamp - self.last_sl_time_low).total_seconds() < self.cooldown_seconds
        )

        if not is_low_in_cooldown and htf_trend != "STRONG_BEARISH":
            if mid_price < r_low:
                penetration = r_low - mid_price
                if self.min_sweep_usd <= penetration <= self.max_sweep_usd:
                    self.low_sweep_active = True
                    self.low_sweep_trough = min(self.low_sweep_trough or mid_price, mid_price)
                elif penetration > self.max_sweep_usd:
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
                    boundary_price=r_low,
                    lot_multiplier=regime.lot_multiplier,
                    max_layers=regime.max_layers,
                )
        else:
            self.low_sweep_active = False

        return None

    def _reset_sweep_state(self):
        self.high_sweep_active = False
        self.high_sweep_peak = 0.0
        self.low_sweep_active = False
        self.low_sweep_trough = 0.0
