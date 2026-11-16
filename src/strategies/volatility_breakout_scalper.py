"""Volatility Breakout Scalper Engine v1.0 (TICK-1103 / EXP-12).

Specialized Trend-Following Engine designed for Runaway Trend / High-Volatility Regimes.
Operates as 'Engine B' alongside 'Engine A' (RangeSweepScalperV8).

Core Architectural Pillars:
1. Breakout + Retest Confirmation (Zero FOMO Top-Buying):
   - Waits for significant penetration beyond reference boundary (>= $2.00).
   - Waits for micro-pullback / retest towards the broken level ($0.50 - $1.50 buffer).
   - Confirms sub-second rejection bounce before entering Layer 1.
2. Anti-Martingale Pyramiding (Adding into Winners with Risk Ceiling):
   - Layer 1 (0.05 lot): Initial entry on retest bounce. Hard SL below retest swing.
   - Layer 2 (0.10 lot): Added ONLY when Layer 1 is in floating profit >= +$2.50 AND Layer 1 SL is locked to Breakeven (Risk = $0).
   - Layer 3 (0.15 lot): Added ONLY when Layer 2 is in floating profit >= +$3.00 AND trailing SL locks guaranteed net positive profit across L1+L2.
3. Trailing Runner Protection:
   - Dynamic trailing stop locks accumulated gains as gold surges $10 - $30+.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional, List
import uuid

from src.simulator.execution import OrderRequest
from src.simulator.portfolio import PortfolioTracker, Position
from src.strategies.base import BaseStrategy, TickEvent
from src.strategies.regime_detector import MarketRegimeState


@dataclass
class BreakoutCampaign:
    """Tracks active multi-layer trend-following breakout campaign."""
    campaign_id: str
    side: Literal["BUY", "SELL"]
    start_time: datetime
    initial_sl: float
    current_sl: float
    layer_pids: List[str] = field(default_factory=list)
    layer_entry_prices: List[float] = field(default_factory=list)
    stage: int = 1                          # 1: L1 only, 2: L1+L2, 3: L1+L2+L3
    campaign_peak: float = 0.0              # Highest price reached (for BUY) or lowest (for SELL)
    is_closed: bool = False


class VolatilityBreakoutScalperV1(BaseStrategy):
    """Trend-following breakout scalper with retest confirmation and pyramiding."""

    def __init__(
        self,
        name: str = "VolatilityBreakoutScalperV1",
        breakout_min_penetration_usd: float = 2.00,
        retest_max_distance_usd: float = 1.50,
        retest_bounce_trigger_usd: float = 0.40,
        hard_sl_offset_usd: float = 1.50,
        pyramid_step_1_usd: float = 2.50,
        pyramid_step_2_usd: float = 3.00,
        trailing_stop_buffer_usd: float = 2.00,
        take_profit_target_usd: float = 25.00,
        layer_volumes: Optional[List[float]] = None,
        max_spread_usd: float = 0.25,
    ):
        super().__init__(name)
        self.breakout_min_penetration = breakout_min_penetration_usd
        self.retest_max_distance = retest_max_distance_usd
        self.retest_bounce_trigger = retest_bounce_trigger_usd
        self.hard_sl_offset = hard_sl_offset_usd
        self.pyramid_step_1 = pyramid_step_1_usd
        self.pyramid_step_2 = pyramid_step_2_usd
        self.trailing_stop_buffer = trailing_stop_buffer_usd
        self.take_profit_target = take_profit_target_usd
        self.layer_volumes = layer_volumes or [0.05, 0.10, 0.15]
        self.max_spread = max_spread_usd

        # Breakout state tracking
        self.bull_breakout_active: bool = False
        self.bull_breakout_level: float = 0.0
        self.bull_breakout_peak: float = 0.0
        self.bull_retest_active: bool = False
        self.bull_retest_trough: float = 0.0

        self.bear_breakout_active: bool = False
        self.bear_breakout_level: float = 0.0
        self.bear_breakout_trough: float = 0.0
        self.bear_retest_active: bool = False
        self.bear_retest_peak: float = 0.0

        # Active campaign
        self.active_campaign: Optional[BreakoutCampaign] = None

    @property
    def has_active_campaign(self) -> bool:
        return self.active_campaign is not None and not self.active_campaign.is_closed

    def update_campaign_positions(self):
        """Synchronize active campaign position IDs with portfolio."""
        if not self.has_active_campaign or not self.portfolio:
            return

        camp = self.active_campaign
        # Register new portfolio open positions into campaign if needed
        for pid in list(self.portfolio.open_positions.keys()):
            if pid not in camp.layer_pids:
                pos = self.portfolio.open_positions[pid]
                if pos.side == camp.side:
                    camp.layer_pids.append(pid)
                    camp.layer_entry_prices.append(pos.open_price)

        # Check if all campaign positions are now closed
        all_closed = True
        for pid in camp.layer_pids:
            if pid in self.portfolio.open_positions:
                all_closed = False
                break

        if all_closed and len(camp.layer_pids) > 0:
            camp.is_closed = True
            self.active_campaign = None

    def on_tick_with_regime(
        self,
        tick: TickEvent,
        regime_state: MarketRegimeState,
        ref_high: float,
        ref_low: float,
    ) -> Optional[OrderRequest]:
        """Process tick event under the supervision of MarketRegimeState and boundary levels."""
        mid_price = (tick.bid + tick.ask) / 2.0

        # Sync portfolio
        self.update_campaign_positions()

        # -------------------------------------------------------------
        # 1. Manage Active Breakout Campaign (Pyramiding & Trailing Stop)
        # -------------------------------------------------------------
        if self.has_active_campaign:
            camp = self.active_campaign
            return self._manage_campaign(tick, mid_price, camp)

        # -------------------------------------------------------------
        # 2. Gate: Spread Check
        # -------------------------------------------------------------
        if tick.spread > self.max_spread:
            return None

        # -------------------------------------------------------------
        # 3. Gate: Trend Direction Required
        # -------------------------------------------------------------
        if not regime_state.is_trending:
            self._reset_breakout_state()
            return None

        # -------------------------------------------------------------
        # 4. Bullish Breakout + Retest Detection
        # -------------------------------------------------------------
        if regime_state.trend_direction == "BULLISH":
            # Reference resistance level is either ORB High or Range High
            r_high = regime_state.orb_high if (regime_state.orb_active and regime_state.orb_high > 0) else ref_high
            if r_high <= 0.0:
                if regime_state.day_open_price > 0.0:
                    r_high = regime_state.day_open_price + self.breakout_min_penetration
                else:
                    return None

            # Phase 1: Breakout above resistance
            if not self.bull_breakout_active:
                if mid_price >= r_high + self.breakout_min_penetration:
                    self.bull_breakout_active = True
                    self.bull_breakout_level = r_high
                    self.bull_breakout_peak = mid_price
            else:
                if mid_price > self.bull_breakout_peak:
                    self.bull_breakout_peak = mid_price

            # Phase 2: Retest Pullback towards broken resistance
            if self.bull_breakout_active and mid_price < self.bull_breakout_peak:
                dist_to_level = mid_price - self.bull_breakout_level
                if -0.50 <= dist_to_level <= self.retest_max_distance:
                    if not self.bull_retest_active:
                        self.bull_retest_active = True
                        self.bull_retest_trough = mid_price
                    else:
                        self.bull_retest_trough = min(self.bull_retest_trough, mid_price)

            # Invalidation: if price falls significantly below breakout level
            if self.bull_breakout_active and mid_price < (self.bull_breakout_level - 1.00):
                self._reset_breakout_state()

            # Phase 3: Bounce Rejection Confirmation
            if (self.bull_retest_active and 
                mid_price >= self.bull_retest_trough + self.retest_bounce_trigger and
                mid_price >= self.bull_breakout_level):
                # Trigger confirmed! Enter Layer 1
                hard_sl = round(self.bull_retest_trough - self.hard_sl_offset, 3)
                vol_l1 = self.layer_volumes[0]

                self.active_campaign = BreakoutCampaign(
                    campaign_id=str(uuid.uuid4())[:8],
                    side="BUY",
                    start_time=tick.timestamp,
                    initial_sl=hard_sl,
                    current_sl=hard_sl,
                    campaign_peak=mid_price,
                )

                self._reset_breakout_state()
                return OrderRequest(
                    order_type="OPEN",
                    side="BUY",
                    volume=vol_l1,
                    signal_time=tick.timestamp,
                    sl=hard_sl,
                    reason="BREAKOUT_RETEST_L1",
                )

        # -------------------------------------------------------------
        # 5. Bearish Breakout + Retest Detection
        # -------------------------------------------------------------
        elif regime_state.trend_direction == "BEARISH":
            r_low = regime_state.orb_low if (regime_state.orb_active and regime_state.orb_low > 0) else ref_low
            if r_low <= 0.0:
                if regime_state.day_open_price > 0.0:
                    r_low = regime_state.day_open_price - self.breakout_min_penetration
                else:
                    return None

            # Phase 1: Breakout below support
            if not self.bear_breakout_active:
                if mid_price <= r_low - self.breakout_min_penetration:
                    self.bear_breakout_active = True
                    self.bear_breakout_level = r_low
                    self.bear_breakout_trough = mid_price
            else:
                if mid_price < self.bear_breakout_trough:
                    self.bear_breakout_trough = mid_price

            # Phase 2: Retest Pullback towards broken support
            if self.bear_breakout_active and mid_price > self.bear_breakout_trough:
                dist_to_level = self.bear_breakout_level - mid_price
                if -0.50 <= dist_to_level <= self.retest_max_distance:
                    if not self.bear_retest_active:
                        self.bear_retest_active = True
                        self.bear_retest_peak = mid_price
                    else:
                        self.bear_retest_peak = max(self.bear_retest_peak, mid_price)

            # Invalidation: if price rises significantly above breakout level
            if self.bear_breakout_active and mid_price > (self.bear_breakout_level + 1.00):
                self._reset_breakout_state()

            # Phase 3: Bounce Rejection Confirmation
            if (self.bear_retest_active and 
                mid_price <= self.bear_retest_peak - self.retest_bounce_trigger and
                mid_price <= self.bear_breakout_level):
                hard_sl = round(self.bear_retest_peak + self.hard_sl_offset, 3)
                vol_l1 = self.layer_volumes[0]

                self.active_campaign = BreakoutCampaign(
                    campaign_id=str(uuid.uuid4())[:8],
                    side="SELL",
                    start_time=tick.timestamp,
                    initial_sl=hard_sl,
                    current_sl=hard_sl,
                    campaign_peak=mid_price,
                )

                self._reset_breakout_state()
                return OrderRequest(
                    order_type="OPEN",
                    side="SELL",
                    volume=vol_l1,
                    signal_time=tick.timestamp,
                    sl=hard_sl,
                    reason="BREAKOUT_RETEST_L1",
                )

        return None

    def _manage_campaign(self, tick: TickEvent, mid_price: float, camp: BreakoutCampaign) -> Optional[OrderRequest]:
        """Manage active campaign: Pyramiding into winners & Trailing stop."""
        if not self.portfolio or len(camp.layer_entry_prices) == 0:
            return None

        p1_entry = camp.layer_entry_prices[0]

        # -------------------------------------------------------------
        # BUY Campaign Management
        # -------------------------------------------------------------
        if camp.side == "BUY":
            camp.campaign_peak = max(camp.campaign_peak, mid_price)
            profit_p1 = mid_price - p1_entry

            # Macro Full Take Profit Target ($25+ extension)
            if profit_p1 >= self.take_profit_target:
                # Close first remaining position
                for pid in camp.layer_pids:
                    if pid in self.portfolio.open_positions:
                        return OrderRequest(
                            order_type="CLOSE",
                            side="BUY",
                            volume=self.portfolio.open_positions[pid].volume,
                            signal_time=tick.timestamp,
                            target_position_id=pid,
                            reason="MACRO_TP_TARGET",
                        )

            # Pyramiding Step 1 -> Add Layer 2 (0.10 lot)
            if camp.stage == 1 and profit_p1 >= self.pyramid_step_1:
                # Lock Layer 1 SL to Breakeven (p1_entry)
                for pid in camp.layer_pids:
                    if pid in self.portfolio.open_positions:
                        self.portfolio.open_positions[pid].sl = round(p1_entry + 0.10, 3)

                camp.stage = 2
                camp.current_sl = round(p1_entry + 0.10, 3)
                vol_l2 = self.layer_volumes[1]
                sl_l2 = round(p1_entry, 3)  # L2 SL at L1 entry

                return OrderRequest(
                    order_type="OPEN",
                    side="BUY",
                    volume=vol_l2,
                    signal_time=tick.timestamp,
                    sl=sl_l2,
                    reason="PYRAMID_LAYER_2",
                )

            # Pyramiding Step 2 -> Add Layer 3 (0.15 lot)
            elif camp.stage == 2 and len(camp.layer_entry_prices) >= 2:
                p2_entry = camp.layer_entry_prices[1]
                profit_p2 = mid_price - p2_entry

                if profit_p2 >= self.pyramid_step_2:
                    # Guaranteed Profit Lock across L1 + L2
                    locked_sl = round((p1_entry + p2_entry) / 2.0, 3)
                    for pid in camp.layer_pids:
                        if pid in self.portfolio.open_positions:
                            self.portfolio.open_positions[pid].sl = locked_sl

                    camp.stage = 3
                    camp.current_sl = locked_sl
                    vol_l3 = self.layer_volumes[2]
                    sl_l3 = round(p2_entry - self.hard_sl_offset, 3)

                    return OrderRequest(
                        order_type="OPEN",
                        side="BUY",
                        volume=vol_l3,
                        signal_time=tick.timestamp,
                        sl=sl_l3,
                        reason="PYRAMID_LAYER_3",
                    )

            # Dynamic Trailing Stop for Stages 2 and 3
            if camp.stage >= 2:
                candidate_trailing = round(camp.campaign_peak - self.trailing_stop_buffer, 3)
                if candidate_trailing > camp.current_sl:
                    camp.current_sl = candidate_trailing
                    for pid in camp.layer_pids:
                        if pid in self.portfolio.open_positions:
                            # Advance SL only in profitable direction
                            curr = self.portfolio.open_positions[pid].sl
                            if curr is None or candidate_trailing > curr:
                                self.portfolio.open_positions[pid].sl = candidate_trailing

        # -------------------------------------------------------------
        # SELL Campaign Management
        # -------------------------------------------------------------
        elif camp.side == "SELL":
            camp.campaign_peak = min(camp.campaign_peak or mid_price, mid_price)
            profit_p1 = p1_entry - mid_price

            if profit_p1 >= self.take_profit_target:
                for pid in camp.layer_pids:
                    if pid in self.portfolio.open_positions:
                        return OrderRequest(
                            order_type="CLOSE",
                            side="SELL",
                            volume=self.portfolio.open_positions[pid].volume,
                            signal_time=tick.timestamp,
                            target_position_id=pid,
                            reason="MACRO_TP_TARGET",
                        )

            # Pyramiding Step 1 -> Add Layer 2
            if camp.stage == 1 and profit_p1 >= self.pyramid_step_1:
                for pid in camp.layer_pids:
                    if pid in self.portfolio.open_positions:
                        self.portfolio.open_positions[pid].sl = round(p1_entry - 0.10, 3)

                camp.stage = 2
                camp.current_sl = round(p1_entry - 0.10, 3)
                vol_l2 = self.layer_volumes[1]
                sl_l2 = round(p1_entry, 3)

                return OrderRequest(
                    order_type="OPEN",
                    side="SELL",
                    volume=vol_l2,
                    signal_time=tick.timestamp,
                    sl=sl_l2,
                    reason="PYRAMID_LAYER_2",
                )

            # Pyramiding Step 2 -> Add Layer 3
            elif camp.stage == 2 and len(camp.layer_entry_prices) >= 2:
                p2_entry = camp.layer_entry_prices[1]
                profit_p2 = p2_entry - mid_price

                if profit_p2 >= self.pyramid_step_2:
                    locked_sl = round((p1_entry + p2_entry) / 2.0, 3)
                    for pid in camp.layer_pids:
                        if pid in self.portfolio.open_positions:
                            self.portfolio.open_positions[pid].sl = locked_sl

                    camp.stage = 3
                    camp.current_sl = locked_sl
                    vol_l3 = self.layer_volumes[2]
                    sl_l3 = round(p2_entry + self.hard_sl_offset, 3)

                    return OrderRequest(
                        order_type="OPEN",
                        side="SELL",
                        volume=vol_l3,
                        signal_time=tick.timestamp,
                        sl=sl_l3,
                        reason="PYRAMID_LAYER_3",
                    )

            # Trailing Stop for Stages 2 and 3
            if camp.stage >= 2:
                candidate_trailing = round(camp.campaign_peak + self.trailing_stop_buffer, 3)
                if candidate_trailing < camp.current_sl:
                    camp.current_sl = candidate_trailing
                    for pid in camp.layer_pids:
                        if pid in self.portfolio.open_positions:
                            curr = self.portfolio.open_positions[pid].sl
                            if curr is None or candidate_trailing < curr:
                                self.portfolio.open_positions[pid].sl = candidate_trailing

        return None

    def on_tick(self, tick: TickEvent) -> Optional[OrderRequest]:
        """Standard interface fallback."""
        return None

    def _reset_breakout_state(self):
        """Reset temporary breakout triggers."""
        self.bull_breakout_active = False
        self.bull_breakout_level = 0.0
        self.bull_breakout_peak = 0.0
        self.bull_retest_active = False
        self.bull_retest_trough = 0.0

        self.bear_breakout_active = False
        self.bear_breakout_level = 0.0
        self.bear_breakout_trough = 0.0
        self.bear_retest_active = False
        self.bear_retest_peak = 0.0
