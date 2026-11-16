"""Macro Daily Trend & Asymmetric Directional Shield Engine v6.0 (EXP-08 / TICK-703).

Alpha synthesis:
1. Restored Range Sweet Spot ($3.00 to $10.00).
2. Time Blackout: News (12:00 UTC), NY Churn (19:00 UTC), Rollover Spreads (21:00-22:59 UTC).
3. Step-Lock Architecture (Layer 1 closes at EQ, Layer 2 closes at opposite edge, Layer 3 runner locked to EQ).
4. Macro Daily Trend & Asymmetric Directional Shield:
   - When Macro H1 EMA-8 vs EMA-24 is STRONG_BULLISH: Blocks counter-trend SELLs at Range High, allows BUYs on Range Low dips.
   - When Macro H1 EMA-8 vs EMA-24 is STRONG_BEARISH: Blocks counter-trend BUYs at Range Low, allows SELLs on Range High rallies.
   - When Macro Regime is BALANCED_SIDEWAY: Allows full dual-direction trading.
"""

from datetime import datetime
from typing import Optional, Set

from src.simulator.execution import OrderRequest
from src.simulator.layer_manager import LayerManager, BEPolicy
from src.strategies.base import BaseStrategy, TickEvent
from src.strategies.macro_trend_detector import MacroTrendDetector, MacroRegimeState
from src.strategies.range_detector import RangeDetector, RangeState


class RangeSweepScalperV6(BaseStrategy):
    """Range Sweep Scalper with Macro Trend Alignment & Asymmetric Directional Shield."""

    DEFAULT_BLACKOUT_HOURS_UTC: Set[int] = {12, 19, 21, 22}

    def __init__(
        self,
        name: str = "RangeSweepScalperV6",
        lookback_minutes: int = 30,
        min_range_usd: float = 3.0,          # Sweet spot: $3.00 minimum
        max_range_usd: float = 10.0,         # Sweet spot: $10.00 maximum
        min_sweep_usd: float = 0.75,         # Liquidity sweep depth threshold ($0.75)
        max_sweep_usd: float = 2.00,         # Runaway breakout cutoff ($2.00)
        hard_sl_offset_usd: float = 1.20,    # Invalidation buffer beyond sweep extreme
        layer_spacing_usd: float = 0.50,     # Retest spacing for Layer 2 & 3
        layer_volumes: Optional[list[float]] = None,
        max_spread_usd: float = 0.25,        # Normal spread tolerance ($0.25)
        cooldown_seconds: float = 1200.0,    # 20-minute cooldown on broken boundary
        be_policy: str = "STEP_LOCK",        # Optimal Breakeven architecture
        blackout_hours_utc: Optional[Set[int]] = None,
        allowed_hours_utc: Optional[Set[int]] = None,
        macro_fast_hours: int = 8,           # Macro Fast EMA (8 hours)
        macro_slow_hours: int = 24,          # Macro Slow EMA (24 hours = 1 day)
        macro_threshold_usd: float = 2.50,   # Macro Trend separation threshold ($2.50)
    ):
        super().__init__(name)
        self.detector = RangeDetector(
            lookback_minutes=lookback_minutes,
            min_range_usd=min_range_usd,
            max_range_usd=max_range_usd,
        )
        self.macro_detector = MacroTrendDetector(
            fast_hours=macro_fast_hours,
            slow_hours=macro_slow_hours,
            trend_threshold_usd=macro_threshold_usd,
        )
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

        # Time Gating Configuration
        if blackout_hours_utc is not None:
            self.blackout_hours_utc = set(blackout_hours_utc)
        else:
            self.blackout_hours_utc = set(self.DEFAULT_BLACKOUT_HOURS_UTC)

        if allowed_hours_utc is not None:
            self.allowed_hours_utc = set(allowed_hours_utc)
        else:
            self.allowed_hours_utc = set(range(24)) - self.blackout_hours_utc

        # Sweep tracking state
        self.high_sweep_active = False
        self.high_sweep_peak = 0.0
        self.low_sweep_active = False
        self.low_sweep_trough = 0.0

        # Boundary cooldown timestamps
        self.last_sl_time_high: Optional[datetime] = None
        self.last_sl_time_low: Optional[datetime] = None

    def on_tick(self, tick: TickEvent) -> Optional[OrderRequest]:
        # 1. Update Macro Daily Trend Detector
        macro_state: MacroRegimeState = self.macro_detector.update(tick.timestamp, tick.bid, tick.ask)

        # 2. Update Range Detector
        range_state: RangeState = self.detector.update(tick.timestamp, tick.bid, tick.ask)
        mid_price = (tick.bid + tick.ask) / 2.0

        # Sync portfolio open positions to layer manager
        if self.portfolio and self.layer_mgr.has_active_setup:
            for pid in self.portfolio.open_positions:
                if pid not in self.layer_mgr.current_setup.active_position_ids:
                    self.layer_mgr.register_position(pid)

        # -------------------------------------------------------------
        # 3. Manage Active Layer Setup (SL, TP1, TP2, Step-Lock Runner)
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
        # 4. Gating: News Release, Afternoon Churn & Rollover Blackout
        # -------------------------------------------------------------
        if tick.timestamp.hour in self.blackout_hours_utc or tick.timestamp.hour not in self.allowed_hours_utc:
            self._reset_sweep_state()
            return None

        # -------------------------------------------------------------
        # 5. Gating: Spread & Ranging Sweet Spot ($3 - $10)
        # -------------------------------------------------------------
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
        # 6. BEARISH SWEEP & TRAP AT RANGE HIGH (SELL SETUP)
        #    Shield: Strictly blocked if Macro Trend is STRONG_BULLISH
        # -------------------------------------------------------------
        is_high_in_cooldown = (
            self.last_sl_time_high is not None
            and (tick.timestamp - self.last_sl_time_high).total_seconds() < self.cooldown_seconds
        )

        can_sell = (
            not is_high_in_cooldown
            and htf_trend != "STRONG_BULLISH"
            and macro_state.allow_sell  # Directional Shield check
        )

        if can_sell:
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
                    lot_multiplier=1.0,
                    max_layers=3,
                )
        else:
            self.high_sweep_active = False

        # -------------------------------------------------------------
        # 7. BULLISH SWEEP & TRAP AT RANGE LOW (BUY SETUP)
        #    Shield: Strictly blocked if Macro Trend is STRONG_BEARISH
        # -------------------------------------------------------------
        is_low_in_cooldown = (
            self.last_sl_time_low is not None
            and (tick.timestamp - self.last_sl_time_low).total_seconds() < self.cooldown_seconds
        )

        can_buy = (
            not is_low_in_cooldown
            and htf_trend != "STRONG_BEARISH"
            and macro_state.allow_buy  # Directional Shield check
        )

        if can_buy:
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
                    lot_multiplier=1.0,
                    max_layers=3,
                )
        else:
            self.low_sweep_active = False

        return None

    def _reset_sweep_state(self):
        self.high_sweep_active = False
        self.high_sweep_peak = 0.0
        self.low_sweep_active = False
        self.low_sweep_trough = 0.0
