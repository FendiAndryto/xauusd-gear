"""Pure Asymmetric Shield Scalper Engine v10.0 (EXP-15 / TICK-1302 / TICK-1303).

Production-grade Quantitative Scalping Engine for XAUUSD:
1. Pure Single-Engine Model:
   - Full elimination of Engine B (No breakout retest churn, zero whipsaw tax).
   - 100% focused on proven asymmetric mean-reversion alpha (30m S/R, $3-$10 range, sweep $0.75-$2.00).
   - Step-Lock Breakeven architecture with 3.22x payoff ratio.
2. In-Line Wasit ORB Protective Shield:
   - London 07:00-08:00 UTC anchor ($4.00 breakout threshold).
   - Operates strictly as a Protective Circuit Breaker:
     * Bullish ORB Breakout: Completely locks and blocks counter-trend SELL fading.
     * Bearish ORB Breakout: Completely locks and blocks counter-trend BUY fading.
3. Enhanced Temporal Gating:
   - Configurable Monday Mode: 'OFF' (default, slashes -$1,277 weekend gap losses) or 'AFTERNOON_ONLY' (>= 12:00 UTC).
   - Extended Blackout Hours: {0, 1, 2, 8, 12, 19, 21, 22} UTC.
4. Execution Hygiene & Anti-Burst Cooldown:
   - Anti-burst layer cooldown (min 60s) to prevent sub-second multi-fill duplicates on tick density spikes.
   - Institutional Daily Circuit Breaker ($150.00 daily loss kill-switch).
   - Strict Base Spread Filter ($0.25).
"""

from datetime import datetime
from typing import Optional, Set

from src.simulator.execution import OrderRequest
from src.simulator.layer_manager import LayerManager, BEPolicy
from src.strategies.base import BaseStrategy, TickEvent
from src.strategies.macro_trend_detector import MacroTrendDetector, MacroRegimeState
from src.strategies.range_detector import RangeDetector, RangeState
from src.strategies.regime_detector import MarketRegimeDetector, MarketRegimeState


class PureShieldScalper(BaseStrategy):
    """Pure Single-Engine Scalper with In-Line ORB Shield & Temporal Gating."""

    DEFAULT_BLACKOUT_HOURS_UTC: Set[int] = {0, 1, 2, 8, 12, 19, 21, 22}

    def __init__(
        self,
        name: str = "PureShieldScalper",
        lookback_minutes: int = 30,
        min_range_usd: float = 3.0,          # Sweet spot: $3.00 minimum
        max_range_usd: float = 10.0,         # Sweet spot: $10.00 maximum
        min_sweep_usd: float = 0.75,         # Liquidity sweep depth threshold ($0.75)
        max_sweep_usd: float = 2.00,         # Runaway breakout cutoff ($2.00)
        hard_sl_offset_usd: float = 1.20,    # Invalidation buffer beyond sweep extreme
        layer_spacing_usd: float = 0.50,     # Retest spacing for Layer 2 & 3
        layer_volumes: Optional[list[float]] = None,
        max_spread_usd: float = 0.25,        # Base spread tolerance ($0.25)
        cooldown_seconds: float = 1200.0,    # 20-minute cooldown on broken boundary
        be_policy: str = "STEP_LOCK",        # Optimal Breakeven architecture
        monday_mode: str = "OFF",            # "OFF", "AFTERNOON_ONLY", "ALL"
        blackout_hours_utc: Optional[Set[int]] = None,
        allowed_hours_utc: Optional[Set[int]] = None,
        orb_start_hour_utc: int = 7,         # London ORB Anchor (07:00 UTC)
        orb_duration_hours: int = 1,         # 1 Hour ORB build (07:00-08:00 UTC)
        orb_threshold_usd: float = 4.00,     # Breakout confirmation threshold ($4.00)
        macro_fast_hours: int = 8,           # Macro Fast EMA (8 hours)
        macro_slow_hours: int = 24,          # Macro Slow EMA (24 hours = 1 day)
        macro_threshold_usd: float = 2.50,   # Macro Trend separation threshold ($2.50)
        max_daily_loss_usd: float = 150.0,   # Institutional Daily Circuit Breaker ($150)
        layer_cooldown_seconds: float = 60.0 # Anti-burst layer cooldown (60 seconds)
    ):
        super().__init__(name)
        self.monday_mode = monday_mode.upper()
        self.min_sweep_usd = min_sweep_usd
        self.max_sweep_usd = max_sweep_usd
        self.hard_sl_offset = hard_sl_offset_usd
        self.max_spread = max_spread_usd
        self.cooldown_seconds = cooldown_seconds
        self.be_policy = be_policy
        self.max_daily_loss_usd = max_daily_loss_usd
        self.layer_cooldown_seconds = layer_cooldown_seconds

        # 1. Structural Range Reference Tracker
        self.detector = RangeDetector(
            lookback_minutes=lookback_minutes,
            min_range_usd=min_range_usd,
            max_range_usd=max_range_usd,
        )

        # 2. In-Line Wasit ORB Shield
        self.orb_detector = MarketRegimeDetector(
            mode="ORB",
            orb_start_hour_utc=orb_start_hour_utc,
            orb_duration_hours=orb_duration_hours,
            orb_threshold_usd=orb_threshold_usd,
            enable_trend_latch=False,  # Engine B eliminated, latch not needed
        )

        # 3. Macro Trend Directional Shield (H1 EMA-8 vs EMA-24)
        self.macro_detector = MacroTrendDetector(
            fast_hours=macro_fast_hours,
            slow_hours=macro_slow_hours,
            trend_threshold_usd=macro_threshold_usd,
        )

        # 4. Asymmetric 3-Layer Position Manager
        self.layer_mgr = LayerManager(
            layer_volumes=layer_volumes or [0.05, 0.10, 0.15],
            layer_spacing_usd=layer_spacing_usd,
            be_policy=be_policy,
        )

        # Time Gating Configuration
        if blackout_hours_utc is not None:
            self.blackout_hours_utc = set(blackout_hours_utc)
        else:
            self.blackout_hours_utc = set(self.DEFAULT_BLACKOUT_HOURS_UTC)

        if allowed_hours_utc is not None:
            self.allowed_hours_utc = set(allowed_hours_utc)
        else:
            self.allowed_hours_utc = set(range(24)) - self.blackout_hours_utc

        # Sweep Detection Transient State
        self.high_sweep_active = False
        self.high_sweep_peak = 0.0
        self.low_sweep_active = False
        self.low_sweep_trough = 0.0

        # Boundary cooldown state
        self.last_sl_time_high: Optional[datetime] = None
        self.last_sl_time_low: Optional[datetime] = None

        # Anti-burst layer timing
        self.last_order_time: Optional[datetime] = None

        # Daily Circuit Breaker State
        self._current_day_str: Optional[str] = None
        self._daily_realized_pnl: float = 0.0
        self._last_processed_closed_index: int = 0
        self._circuit_breaker_tripped: bool = False

    def _update_daily_circuit_breaker(self, timestamp: datetime):
        """Update daily PnL tracker and trip circuit breaker if loss exceeds threshold."""
        day_str = timestamp.strftime("%Y-%m-%d")
        if day_str != self._current_day_str:
            # New calendar day (00:00 UTC rollover)
            self._current_day_str = day_str
            self._daily_realized_pnl = 0.0
            self._circuit_breaker_tripped = False
            if self.portfolio:
                self._last_processed_closed_index = len(self.portfolio.closed_positions)

        # Process newly closed trades incrementally
        if self.portfolio and self._last_processed_closed_index < len(self.portfolio.closed_positions):
            while self._last_processed_closed_index < len(self.portfolio.closed_positions):
                pos = self.portfolio.closed_positions[self._last_processed_closed_index]
                self._daily_realized_pnl += pos.pnl_net
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
        """Process incoming tick event with Protective ORB Shield & Temporal Filters."""
        mid_price = (tick.bid + tick.ask) / 2.0

        # -------------------------------------------------------------
        # 1. Update Daily Circuit Breaker Status
        # -------------------------------------------------------------
        self._update_daily_circuit_breaker(tick.timestamp)

        # -------------------------------------------------------------
        # 2. Update Structural Range, Macro Trend & In-Line ORB Detectors
        # -------------------------------------------------------------
        range_state: RangeState = self.detector.update(tick.timestamp, tick.bid, tick.ask)
        macro_state: MacroRegimeState = self.macro_detector.update(tick.timestamp, tick.bid, tick.ask)
        orb_state: MarketRegimeState = self.orb_detector.update(tick.timestamp, tick.bid, tick.ask)

        # Sync portfolio open positions to layer manager
        if self.portfolio and self.layer_mgr.has_active_setup:
            for pid in self.portfolio.open_positions:
                if pid not in self.layer_mgr.current_setup.active_position_ids:
                    self.layer_mgr.register_position(pid)

        # -------------------------------------------------------------
        # 3. Manage Active 3-Layer Setup (Retests, Partial TP, Step-Lock BE)
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
        # 5. Gating: Monday Mode Filter
        # -------------------------------------------------------------
        weekday = tick.timestamp.weekday()  # 0=Monday, ..., 6=Sunday
        if weekday == 0:
            if self.monday_mode == "OFF":
                self._reset_sweep_state()
                return None
            elif self.monday_mode == "AFTERNOON_ONLY" and tick.timestamp.hour < 12:
                self._reset_sweep_state()
                return None

        # -------------------------------------------------------------
        # 6. Gating: Extended Time Blackouts ({0, 1, 2, 8, 12, 19, 21, 22} UTC)
        # -------------------------------------------------------------
        if tick.timestamp.hour in self.blackout_hours_utc or tick.timestamp.hour not in self.allowed_hours_utc:
            self._reset_sweep_state()
            return None

        # -------------------------------------------------------------
        # 7. Gating: Base Spread & Ranging Sweet Spot ($3.00 - $10.00)
        # -------------------------------------------------------------
        if tick.spread > self.max_spread:
            return None

        if not range_state.is_ranging or range_state.circuit_breaker_active:
            self._reset_sweep_state()
            return None

        # -------------------------------------------------------------
        # 8. Anti-Burst Cooldown Check
        # -------------------------------------------------------------
        if self.last_order_time is not None:
            elapsed = (tick.timestamp - self.last_order_time).total_seconds()
            if elapsed < self.layer_cooldown_seconds:
                return None

        r_high = range_state.range_high
        r_low = range_state.range_low
        eq = range_state.equilibrium
        htf_trend = range_state.htf_trend

        # -------------------------------------------------------------
        # 9. Protective Wasit ORB Shield Directional Check
        #    - If London ORB broke out Bullish: BLOCK ALL SELL FADES!
        #    - If London ORB broke out Bearish: BLOCK ALL BUY FADES!
        # -------------------------------------------------------------
        orb_allows_sell = True
        orb_allows_buy = True

        if orb_state.is_trending:
            if orb_state.trend_direction == "BULLISH":
                orb_allows_sell = False  # DO NOT fade a strong bullish breakout!
            elif orb_state.trend_direction == "BEARISH":
                orb_allows_buy = False   # DO NOT fade a strong bearish breakout!

        # -------------------------------------------------------------
        # 10. BEARISH SWEEP & TRAP AT RANGE HIGH (SELL SETUP)
        #     Shields: Blocked if ORB Bullish, Macro Bullish, or HTF Bullish
        # -------------------------------------------------------------
        is_high_in_cooldown = (
            self.last_sl_time_high is not None
            and (tick.timestamp - self.last_sl_time_high).total_seconds() < self.cooldown_seconds
        )

        can_sell = (
            not is_high_in_cooldown
            and orb_allows_sell
            and htf_trend != "STRONG_BULLISH"
            and macro_state.allow_sell
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
                self.last_order_time = tick.timestamp

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
        # 11. BULLISH SWEEP & TRAP AT RANGE LOW (BUY SETUP)
        #     Shields: Blocked if ORB Bearish, Macro Bearish, or HTF Bearish
        # -------------------------------------------------------------
        is_low_in_cooldown = (
            self.last_sl_time_low is not None
            and (tick.timestamp - self.last_sl_time_low).total_seconds() < self.cooldown_seconds
        )

        can_buy = (
            not is_low_in_cooldown
            and orb_allows_buy
            and htf_trend != "STRONG_BEARISH"
            and macro_state.allow_buy
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
                self.last_order_time = tick.timestamp

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
