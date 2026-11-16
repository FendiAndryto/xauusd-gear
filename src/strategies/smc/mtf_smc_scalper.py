"""Standalone Multi-Timeframe SMC Scalper Master Strategy.

Orchestrates D1 Boundaries, H1 Order Flow, M5/M1 CHoCH, Layered Pyramid Order Blocks,
Hybrid Exits (50% + BEP), and Daily Financial Circuit Breakers.
"""

from datetime import datetime
from typing import Optional

from src.simulator.execution import OrderRequest
from src.simulator.portfolio import PortfolioTracker
from src.strategies.base import BaseStrategy, TickEvent
from src.strategies.smc.d1_boundary_extractor import D1BoundaryExtractor, D1Boundary
from src.strategies.smc.h1_bias_classifier import H1BiasClassifier, BiasDirection
from src.strategies.smc.sweep_acceptance_engine import SweepAcceptanceEngine, ReactionType, M5Bar
from src.strategies.smc.order_block_mapper import OrderBlockMapper, ChochEvent, ObType
from src.strategies.smc.pyramid_limit_manager import PyramidLimitManager
from src.strategies.smc.hybrid_exit_manager import HybridExitManager
from src.strategies.smc.daily_financial_guard import DailyFinancialGuard, GuardState


class MtfSmcScalper(BaseStrategy):
    """High-performance multi-timeframe SMC scalper operating on tick streaming events."""

    def __init__(
        self,
        name: str = "MtfSmcScalper",
        daily_profit_cap_pct: float = 0.10,     # +10% daily win cap
        daily_loss_limit_pct: float = 0.10,     # -10% circuit breaker
        risk_layer1_pct: float = 0.010,         # 1.0% Open OB
        risk_layer2_pct: float = 0.015,         # 1.5% 50% Mean Threshold OB
        max_spread_pips: float = 3.5,           # 3.5 pips = $0.35 USD
        min_wick_ratio: float = 0.35,           # Wick ratio threshold for sweep
        spread_buffer_usd: float = 0.25,        # SL buffer beyond sweep extreme
    ):
        super().__init__(name=name)
        self.d1_extractor = D1BoundaryExtractor()
        self.h1_classifier = H1BiasClassifier()
        self.sweep_engine = SweepAcceptanceEngine(min_wick_ratio=min_wick_ratio)
        self.ob_mapper = OrderBlockMapper()
        self.limit_manager = PyramidLimitManager(
            risk_layer1_pct=risk_layer1_pct,
            risk_layer2_pct=risk_layer2_pct,
            spread_buffer_usd=spread_buffer_usd,
        )
        self.exit_manager = HybridExitManager()
        self.fin_guard = DailyFinancialGuard(
            daily_profit_cap_pct=daily_profit_cap_pct,
            daily_loss_limit_pct=daily_loss_limit_pct,
            max_spread_pips=max_spread_pips,
        )

        # Streaming M5 bar aggregator
        self.current_m5_bar: Optional[M5Bar] = None
        self.active_reaction: ReactionType = ReactionType.NONE
        self.active_sweep_extreme: float = 0.0
        self.reaction_expiry: Optional[datetime] = None
        self.queued_signals: list[OrderRequest] = []
        self.cooldown_until: Optional[datetime] = None
        self.daily_setup_losses: int = 0
        self.last_closed_count: int = 0
        self.active_calendar_day = None

    def on_tick(self, tick: TickEvent) -> Optional[OrderRequest]:
        """Core streaming event loop called on every single tick arrival."""
        if self.portfolio is None:
            return None

        # -----------------------------------------------------------------
        # 1. Financial Circuit Breaker & Profit Cap Evaluation
        # -----------------------------------------------------------------
        tick_day = tick.timestamp.date()
        if self.active_calendar_day is None or tick_day != self.active_calendar_day:
            self.active_calendar_day = tick_day
            self.daily_setup_losses = 0

        if len(self.portfolio.closed_positions) > self.last_closed_count:
            new_closed = self.portfolio.closed_positions[self.last_closed_count:]
            self.last_closed_count = len(self.portfolio.closed_positions)
            for c in new_closed:
                if c.pnl_net < -5.0:
                    self.daily_setup_losses += 1

        # If >= 6 order losses (approx 2 full setups) today, trip circuit breaker for the day
        if self.daily_setup_losses >= 6:
            self.limit_manager.clear_all()
            return None

        guard_state = self.fin_guard.on_tick(tick.timestamp, tick.spread, self.portfolio)

        if guard_state in (GuardState.DAILY_CAP_REACHED, GuardState.CIRCUIT_BREAKER_TRIPPED):
            self.limit_manager.clear_all()
            # If positions are still open, close them immediately
            if self.portfolio.open_positions:
                pos_id = next(iter(self.portfolio.open_positions.keys()))
                pos = self.portfolio.open_positions[pos_id]
                return OrderRequest(
                    order_type="CLOSE",
                    side=pos.side,
                    volume=pos.volume,
                    signal_time=tick.timestamp,
                    target_position_id=pos_id,
                    reason=f"DAILY_{guard_state.value}",
                )
            return None

        if guard_state == GuardState.SPREAD_TOO_HIGH:
            # Spread spike: freeze new order execution
            return None

        # -----------------------------------------------------------------
        # 2. Update D1 Boundaries & H1 Order Flow
        # -----------------------------------------------------------------
        active_d1 = self.d1_extractor.on_tick(tick.timestamp, tick.bid, tick.volume)
        h1_bias = self.h1_classifier.on_tick(tick.timestamp, tick.bid, tick.volume)

        if active_d1 is None:
            return None

        # -----------------------------------------------------------------
        # 3. Hybrid Exit Management (Move runner SL to BEP at Milestone 1)
        # -----------------------------------------------------------------
        self.exit_manager.update(
            portfolio=self.portfolio,
            current_bid=tick.bid,
            current_ask=tick.ask,
            equilibrium_level=active_d1.equilibrium,
        )

        # -----------------------------------------------------------------
        # 4. Check Pending Limit Orders for Mitigation Fill
        # -----------------------------------------------------------------
        fill_signals = self.limit_manager.on_tick(tick.timestamp, tick.bid, tick.ask)
        if fill_signals:
            self.queued_signals.extend(fill_signals)

        # -----------------------------------------------------------------
        # 5. Build M5 Bar & Evaluate Swings / CHoCH / Order Blocks
        # -----------------------------------------------------------------
        self._update_m5_bar(tick, active_d1, h1_bias)

        # -----------------------------------------------------------------
        # 6. Emit Queued Signals
        # -----------------------------------------------------------------
        if self.queued_signals:
            return self.queued_signals.pop(0)

        return None

    def _update_m5_bar(self, tick: TickEvent, boundary: D1Boundary, h1_bias: BiasDirection):
        """Aggregate 5-minute bar and trigger SMC detection on bar close."""
        minute_floor = (tick.timestamp.minute // 5) * 5
        bar_start = tick.timestamp.replace(minute=minute_floor, second=0, microsecond=0)

        if self.current_m5_bar is None:
            self.current_m5_bar = M5Bar(
                start_time=bar_start,
                open=tick.bid,
                high=tick.bid,
                low=tick.bid,
                close=tick.bid,
                volume=tick.volume,
            )
            return

        # Check reaction expiration (max 20 mins / 4 bars)
        from datetime import timedelta
        if self.reaction_expiry and tick.timestamp > self.reaction_expiry:
            self.active_reaction = ReactionType.NONE
            self.reaction_expiry = None

        if bar_start > self.current_m5_bar.start_time:
            # Completed M5 bar!
            completed_bar = self.current_m5_bar

            # Check midnight warmup (00:00 - 00:15 UTC) and cooldown
            in_cooldown = self.cooldown_until is not None and tick.timestamp < self.cooldown_until
            in_midnight_warmup = tick.timestamp.hour == 0 and tick.timestamp.minute < 15
            has_pending_or_open = len(self.limit_manager.pending_layers) > 0 or len(self.portfolio.open_positions) >= 4

            if not in_cooldown and not in_midnight_warmup and not has_pending_or_open:
                # 1. Evaluate reaction at D1 boundaries (Sweep vs Acceptance)
                rx_type, extreme = self.sweep_engine.evaluate_bar(completed_bar, boundary)
                if rx_type != ReactionType.NONE:
                    self.active_reaction = rx_type
                    self.active_sweep_extreme = extreme
                    self.reaction_expiry = tick.timestamp + timedelta(minutes=20)

                # 2. Check for CHoCH & map fresh Order Block
                choch: Optional[ChochEvent] = self.ob_mapper.on_bar_completed(
                    completed_bar,
                    self.active_reaction,
                    self.active_sweep_extreme,
                )

                if choch is not None and self.portfolio is not None:
                    # Enforce Trend Alignment & Protect Against Counter-Trend Breakout Traps
                    setup_side = choch.order_block.side
                    allow = True

                    # 1. Block Breakouts against dominant macro bias
                    if choch.order_block.ob_type == ObType.BREAKER_BULL and h1_bias == BiasDirection.BEARISH:
                        allow = False
                    elif choch.order_block.ob_type == ObType.BREAKER_BEAR and h1_bias == BiasDirection.BULLISH:
                        allow = False
                    # 2. Reversals must align with order flow unless high-conviction absorption
                    elif h1_bias == BiasDirection.BULLISH and setup_side == "SELL" and choch.order_block.ob_type != ObType.BEARISH_OB:
                        allow = False
                    elif h1_bias == BiasDirection.BEARISH and setup_side == "BUY" and choch.order_block.ob_type != ObType.BULLISH_OB:
                        allow = False

                    if allow:
                        # Cancel any pending limits that oppose this new structural direction
                        self.limit_manager.cancel_on_opposite_choch(setup_side)

                        # Determine target levels based on setup type (Reversal vs Breakout vs Asian S/R)
                        if setup_side == "SELL":
                            if choch.order_block.ob_type == ObType.BREAKER_BEAR:
                                # Breakdown expansion below PDL
                                eq_tp = round(choch.order_block.open_price - 4.0, 2)
                                runner_tp = round(choch.order_block.open_price - 8.0, 2)
                            elif self.active_reaction == ReactionType.SWEEP_REJECTION_ASIA_HIGH and boundary.asia_high and boundary.asia_low:
                                # Asian Session High sweep targets Asian Equilibrium & Asian Low
                                asia_mid = round((boundary.asia_high + boundary.asia_low) / 2.0, 2)
                                eq_tp = asia_mid
                                runner_tp = boundary.asia_low
                            else:
                                # Reversal sweep from PDH
                                eq_tp = boundary.equilibrium
                                runner_tp = boundary.pdl
                        else:  # BUY
                            if choch.order_block.ob_type == ObType.BREAKER_BULL:
                                # Breakout expansion above PDH
                                eq_tp = round(choch.order_block.open_price + 4.0, 2)
                                runner_tp = round(choch.order_block.open_price + 8.0, 2)
                            elif self.active_reaction == ReactionType.SWEEP_REJECTION_ASIA_LOW and boundary.asia_high and boundary.asia_low:
                                # Asian Session Low sweep targets Asian Equilibrium & Asian High
                                asia_mid = round((boundary.asia_high + boundary.asia_low) / 2.0, 2)
                                eq_tp = asia_mid
                                runner_tp = boundary.asia_high
                            else:
                                # Reversal sweep from PDL
                                eq_tp = boundary.equilibrium
                                runner_tp = boundary.pdh

                        # Generate layered pending limits (Open OB + 50% Mean Threshold)
                        self.limit_manager.create_pyramid_orders(
                            ob=choch.order_block,
                            current_time=tick.timestamp,
                            equity=self.portfolio.balance,
                            equilibrium_tp=eq_tp,
                            opposite_boundary_tp=runner_tp,
                        )

                        # Set 30-minute cooldown
                        self.cooldown_until = tick.timestamp + timedelta(minutes=30)

                        # Reset reaction until next sweep occurs
                        self.active_reaction = ReactionType.NONE
                        self.reaction_expiry = None

            # Start new M5 bar
            self.current_m5_bar = M5Bar(
                start_time=bar_start,
                open=tick.bid,
                high=tick.bid,
                low=tick.bid,
                close=tick.bid,
                volume=tick.volume,
            )
        else:
            self.current_m5_bar.high = max(self.current_m5_bar.high, tick.bid)
            self.current_m5_bar.low = min(self.current_m5_bar.low, tick.bid)
            self.current_m5_bar.close = tick.bid
            self.current_m5_bar.volume += tick.volume
