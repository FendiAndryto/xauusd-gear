"""Daily Circuit Breaker & Macro Volatility Protection Engine v8.0 (EXP-11 / TICK-1002).

Alpha & Risk Management Architecture:
1. All proven V6 Alpha:
   - 30-Minute Range Sweet Spot ($3.00 to $10.00).
   - Instantaneous Sub-Second Tick Rejection ($0.75 - $2.00 sweep).
   - Time Blackouts: News (12:00 UTC), Wall St Churn (19:00 UTC), Rollover Spreads (21:00-22:59 UTC).
   - Step-Lock Runner (L1 @ EQ, L2 @ Opposite, L3 locked to EQ at TP2).
   - Macro Daily Trend & Asymmetric Directional Shield (H1 EMA-8 vs EMA-24).
2. Phase J Innovation: Daily Circuit Breaker (Institutional Day-Loss Kill-Switch)
   - Tracks daily cumulative realized PnL in real-time ($O(1)$).
   - When daily realized loss reaches `max_daily_loss_usd` (default: $150.00), the bot
     automatically TRIPS the circuit breaker and blocks all new trade entries for the remainder of the day.
   - Resets automatically at 00:00 UTC on the next calendar day.
   - Prevents the "Spiral of Death" on violent runaway / high-volatility trend days.
"""

from datetime import datetime
from typing import Optional, Set

from src.simulator.execution import OrderRequest
from src.simulator.layer_manager import LayerManager, BEPolicy
from src.strategies.base import BaseStrategy, TickEvent
from src.strategies.macro_trend_detector import MacroTrendDetector, MacroRegimeState
from src.strategies.range_detector import RangeDetector, RangeState


class RangeSweepScalperV8(BaseStrategy):
    """Range Sweep Scalper with Macro Trend Shield & Daily Circuit Breaker."""

    DEFAULT_BLACKOUT_HOURS_UTC: Set[int] = {12, 19, 21, 22}

    def __init__(
        self,
        name: str = "RangeSweepScalperV8",
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
        max_daily_loss_usd: float = 150.0,   # Institutional Daily Circuit Breaker ($150)
        max_bear_disp_usd: float = 10.00,    # Daily Bearish Expansion Gate ($10.00 below day open)
        max_bull_disp_usd: float = 25.00,    # Daily Bullish Expansion Gate ($25.00 above day open)
        max_distinct_sls_per_day: int = 2,   # Boundary Fatigue Guard (max distinct setup SLs per day)
        midnight_warmup_minutes: int = 15,   # Midnight Session Boundary Maturity Check (00:00-00:15 UTC)
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
        self.layer_spacing = layer_spacing_usd
        self.layer_volumes = layer_volumes or [0.05, 0.10, 0.15]
        self.max_spread = max_spread_usd
        self.cooldown_seconds = cooldown_seconds
        self.be_policy = be_policy
        self.max_daily_loss_usd = max_daily_loss_usd
        self.max_bear_disp_usd = max_bear_disp_usd
        self.max_bull_disp_usd = max_bull_disp_usd
        self.max_distinct_sls_per_day = max_distinct_sls_per_day
        self.midnight_warmup_minutes = midnight_warmup_minutes

        # Time Gating Configuration
        if blackout_hours_utc is not None:
            self.blackout_hours_utc = set(blackout_hours_utc)
        else:
            self.blackout_hours_utc = set(self.DEFAULT_BLACKOUT_HOURS_UTC)

        if allowed_hours_utc is not None:
            self.allowed_hours_utc = set(allowed_hours_utc)
        else:
            self.allowed_hours_utc = set(range(24)) - self.blackout_hours_utc

        # Sweep Detection State
        self.high_sweep_active = False
        self.high_sweep_peak = 0.0
        self.low_sweep_active = False
        self.low_sweep_trough = 0.0

        # Boundary cooldown state
        self.last_sl_time_high: Optional[datetime] = None
        self.last_sl_time_low: Optional[datetime] = None

        # Daily Circuit Breaker & Boundary Fatigue State
        self._current_day_str: Optional[str] = None
        self._daily_realized_pnl: float = 0.0
        self._last_processed_closed_index: int = 0
        self._circuit_breaker_tripped: bool = False

        self._day_open_price: Optional[float] = None
        self._daily_high_sl_events: int = 0
        self._daily_low_sl_events: int = 0
        self._last_sl_event_time_high: Optional[datetime] = None
        self._last_sl_event_time_low: Optional[datetime] = None

    def _update_daily_circuit_breaker(self, timestamp: datetime, mid_price: float):
        """Update daily PnL tracker, day open reference, and setup-level fatigue counters."""
        day_str = timestamp.strftime("%Y-%m-%d")
        if day_str != self._current_day_str:
            # New calendar day (00:00 UTC rollover)
            self._current_day_str = day_str
            self._daily_realized_pnl = 0.0
            self._circuit_breaker_tripped = False
            self._day_open_price = mid_price
            self._daily_high_sl_events = 0
            self._daily_low_sl_events = 0
            self._last_sl_event_time_high = None
            self._last_sl_event_time_low = None
            if self.portfolio:
                self._last_processed_closed_index = len(self.portfolio.closed_positions)

        if self._day_open_price is None:
            self._day_open_price = mid_price

        # Process newly closed trades incrementally
        if self.portfolio and self._last_processed_closed_index < len(self.portfolio.closed_positions):
            while self._last_processed_closed_index < len(self.portfolio.closed_positions):
                pos = self.portfolio.closed_positions[self._last_processed_closed_index]
                self._daily_realized_pnl += pos.pnl_net

                # Track distinct setup invalidations (grouped within 60s)
                if pos.pnl_net < 0 and pos.close_reason in ("HARD_INVALIDATION_SL", "SL"):
                    if pos.side == "SELL":
                        if self._last_sl_event_time_high is None or (pos.close_time - self._last_sl_event_time_high).total_seconds() > 60.0:
                            self._daily_high_sl_events += 1
                            self._last_sl_event_time_high = pos.close_time
                    else:
                        if self._last_sl_event_time_low is None or (pos.close_time - self._last_sl_event_time_low).total_seconds() > 60.0:
                            self._daily_low_sl_events += 1
                            self._last_sl_event_time_low = pos.close_time

                self._last_processed_closed_index += 1

            if self.max_daily_loss_usd > 0 and self._daily_realized_pnl <= -self.max_daily_loss_usd:
                self._circuit_breaker_tripped = True

    @property
    def is_circuit_breaker_tripped(self) -> bool:
        """Returns True if trading is halted for the rest of today."""
        return self._circuit_breaker_tripped

    @property
    def daily_realized_pnl(self) -> float:
        """Returns today's accumulated realized PnL."""
        return self._daily_realized_pnl

    def notify_stop_loss_hit(self, boundary_price: float, side: str, timestamp: datetime):
        """Notify scalper that a stop loss was hit to initiate boundary cooldown."""
        if side == "SELL":
            self.last_sl_time_high = timestamp
            self.high_sweep_active = False
            self.high_sweep_peak = 0.0
        elif side == "BUY":
            self.last_sl_time_low = timestamp
            self.low_sweep_active = False
            self.low_sweep_trough = float("inf")

    def _reset_sweep_state(self):
        """Reset transient sweep detection variables."""
        self.high_sweep_active = False
        self.high_sweep_peak = 0.0
        self.low_sweep_active = False
        self.low_sweep_trough = 0.0

    def on_tick(self, tick: TickEvent) -> Optional[OrderRequest]:
        """Process incoming tick event with Daily Circuit Breaker & Directional Shield."""
        mid_price = (tick.bid + tick.ask) / 2.0

        # -------------------------------------------------------------
        # 1. Update Daily Circuit Breaker Status
        # -------------------------------------------------------------
        self._update_daily_circuit_breaker(tick.timestamp, mid_price)

        # -------------------------------------------------------------
        # 2. Update Higher Timeframe Range & Macro Trend Detectors
        # -------------------------------------------------------------
        range_state: RangeState = self.detector.update(tick.timestamp, tick.bid, tick.ask)
        macro_state: MacroRegimeState = self.macro_detector.update(tick.timestamp, tick.bid, tick.ask)

        # Sync portfolio open positions to layer manager
        if self.portfolio and self.layer_mgr.has_active_setup:
            for pid in self.portfolio.open_positions:
                if pid not in self.layer_mgr.current_setup.active_position_ids:
                    self.layer_mgr.register_position(pid)

        # -------------------------------------------------------------
        # 3. Manage Active 3-Layer Position Setup (Retests, Partial TP, Step-Lock BE)
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
        # 4. Gating: Daily Circuit Breaker Halted (Trend Day Protection)
        # -------------------------------------------------------------
        if self._circuit_breaker_tripped:
            self._reset_sweep_state()
            return None

        # -------------------------------------------------------------
        # 5. Gating: News Release, Afternoon Churn & Rollover Blackout
        # -------------------------------------------------------------
        if tick.timestamp.hour in self.blackout_hours_utc or tick.timestamp.hour not in self.allowed_hours_utc:
            self._reset_sweep_state()
            return None

        # -------------------------------------------------------------
        # 5b. Gating: Midnight Rollover Warmup (00:00 to 00:XX UTC)
        # -------------------------------------------------------------
        if self.midnight_warmup_minutes > 0 and tick.timestamp.hour == 0 and tick.timestamp.minute < self.midnight_warmup_minutes:
            self._reset_sweep_state()
            return None

        # -------------------------------------------------------------
        # 6. Gating: Spread & Ranging Sweet Spot ($3 - $10)
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

        # Directional & Boundary Fatigue Controls
        day_disp = (mid_price - self._day_open_price) if self._day_open_price is not None else 0.0
        can_sell_boundary = (self._daily_high_sl_events < self.max_distinct_sls_per_day) if self.max_distinct_sls_per_day > 0 else True
        can_buy_boundary = (self._daily_low_sl_events < self.max_distinct_sls_per_day) if self.max_distinct_sls_per_day > 0 else True

        # -------------------------------------------------------------
        # 7. BEARISH SWEEP & TRAP AT RANGE HIGH (SELL SETUP)
        #    Shield: Strictly blocked if Macro Trend is STRONG_BULLISH or High Boundary Fatigued
        # -------------------------------------------------------------
        is_high_in_cooldown = (
            self.last_sl_time_high is not None
            and (tick.timestamp - self.last_sl_time_high).total_seconds() < self.cooldown_seconds
        )

        can_sell = (
            can_sell_boundary
            and not is_high_in_cooldown
            and htf_trend != "STRONG_BULLISH"
            and macro_state.allow_sell  # Directional Shield check
            and not (self.max_bull_disp_usd > 0 and day_disp >= self.max_bull_disp_usd)
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
        # 8. BULLISH SWEEP & TRAP AT RANGE LOW (BUY SETUP)
        #    Shield: Strictly blocked if Macro Trend is STRONG_BEARISH,
        #            Low Boundary Fatigued, or Daily Bearish Expansion Gate tripped
        # -------------------------------------------------------------
        is_low_in_cooldown = (
            self.last_sl_time_low is not None
            and (tick.timestamp - self.last_sl_time_low).total_seconds() < self.cooldown_seconds
        )

        can_buy = (
            can_buy_boundary
            and not is_low_in_cooldown
            and htf_trend != "STRONG_BEARISH"
            and macro_state.allow_buy  # Directional Shield check
            and not (self.max_bear_disp_usd > 0 and day_disp <= -self.max_bear_disp_usd)
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
