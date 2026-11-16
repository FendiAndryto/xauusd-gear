"""Adaptive Dual-Engine Regime-Switching Scalper (TICK-1104 / EXP-12).

Orchestrates two orthogonal, complementary quant engines:
- Engine A: RangeSweepScalperV8 (Mean-reversion specialist in sideway/normal regimes).
- Engine B: VolatilityBreakoutScalperV1 (Momentum breakout & pyramiding specialist in trend regimes).
Supervised by MarketRegimeDetector (ORB / Daily Expansion / EMA Slope) and Global Daily Circuit Breaker.
"""

from datetime import datetime
from typing import Optional, Set

from src.simulator.execution import OrderRequest
from src.simulator.portfolio import PortfolioTracker
from src.strategies.base import BaseStrategy, TickEvent
from src.strategies.range_detector import RangeDetector, RangeState
from src.strategies.range_sweep_scalper_v8 import RangeSweepScalperV8
from src.strategies.regime_detector import MarketRegimeDetector, MarketRegimeState
from src.strategies.volatility_breakout_scalper import VolatilityBreakoutScalperV1


class AdaptiveDualEngineScalper(BaseStrategy):
    """Adaptive Dual-Engine Scalper with Institutional Regime Switching."""

    DEFAULT_BLACKOUT_HOURS_UTC: Set[int] = {12, 19, 21, 22}
    EXTENDED_BLACKOUT_HOURS_UTC: Set[int] = {0, 1, 2, 8, 12, 19, 21, 22}

    def __init__(
        self,
        name: str = "AdaptiveDualEngineScalper",
        regime_mode: str = "DYNAMIC_EXPANSION",
        daily_expansion_threshold_usd: float = 15.00,
        orb_start_hour_utc: int = 7,
        orb_threshold_usd: float = 3.00,
        max_daily_loss_usd: float = 150.0,
        max_spread_usd: float = 0.25,
        engine_a: Optional[RangeSweepScalperV8] = None,
        engine_b: Optional[VolatilityBreakoutScalperV1] = None,
        blackout_hours_utc: Optional[Set[int]] = None,
        disable_monday: bool = False,
        enable_trend_latch: bool = False,
    ):
        super().__init__(name)
        self.regime_mode = regime_mode
        self.max_daily_loss_usd = max_daily_loss_usd
        self.max_spread = max_spread_usd
        self.disable_monday = disable_monday
        self.enable_trend_latch = enable_trend_latch

        if blackout_hours_utc is not None:
            self.blackout_hours_utc = set(blackout_hours_utc)
        else:
            self.blackout_hours_utc = set(self.DEFAULT_BLACKOUT_HOURS_UTC)

        # 1. Market Regime Switchboard (Wasit)
        self.regime_detector = MarketRegimeDetector(
            mode=regime_mode,
            daily_expansion_threshold_usd=daily_expansion_threshold_usd,
            orb_start_hour_utc=orb_start_hour_utc,
            orb_threshold_usd=orb_threshold_usd,
            enable_trend_latch=enable_trend_latch,
        )

        # 2. Structural Range Reference Tracker
        self.range_detector = RangeDetector(
            lookback_minutes=30,
            min_range_usd=3.0,
            max_range_usd=10.0,
        )

        # 3. Engine A (Mean-Reversion Sweep Scalper)
        self.engine_a = engine_a or RangeSweepScalperV8(
            max_daily_loss_usd=max_daily_loss_usd,
            max_spread_usd=max_spread_usd,
            blackout_hours_utc=self.blackout_hours_utc,
        )

        # 4. Engine B (Volatility Breakout & Pyramiding Scalper)
        self.engine_b = engine_b or VolatilityBreakoutScalperV1(
            max_spread_usd=max_spread_usd,
        )

        # Daily Circuit Breaker State (Global Portfolio level)
        self._current_day_str: Optional[str] = None
        self._day_starting_balance: float = 10_000.0
        self._last_closed_trades_count: int = 0
        self._daily_realized_loss: float = 0.0
        self._circuit_breaker_tripped: bool = False

    def set_portfolio(self, portfolio: PortfolioTracker):
        """Propagate shared portfolio reference to both engines."""
        super().set_portfolio(portfolio)
        self.engine_a.set_portfolio(portfolio)
        self.engine_b.set_portfolio(portfolio)
        self._day_starting_balance = portfolio.balance

    def _update_global_circuit_breaker(self, timestamp: datetime):
        """Track daily portfolio-level realized loss in O(1) time."""
        if not self.portfolio:
            return

        day_str = timestamp.strftime("%Y-%m-%d")
        if self._current_day_str != day_str:
            # New calendar day (00:00 UTC) -> Reset Circuit Breaker
            self._current_day_str = day_str
            self._day_starting_balance = self.portfolio.balance
            self._last_closed_trades_count = len(self.portfolio.closed_positions)
            self._daily_realized_loss = 0.0
            self._circuit_breaker_tripped = False
            return

        # Incrementally tally trades closed today
        current_closed_count = len(self.portfolio.closed_positions)
        if current_closed_count > self._last_closed_trades_count:
            for i in range(self._last_closed_trades_count, current_closed_count):
                pos = self.portfolio.closed_positions[i]
                net = pos.pnl_net
                if net < 0:
                    self._daily_realized_loss += abs(net)
                else:
                    self._daily_realized_loss = max(0.0, self._daily_realized_loss - net)
            self._last_closed_trades_count = current_closed_count

        if self._daily_realized_loss >= self.max_daily_loss_usd:
            self._circuit_breaker_tripped = True

    def on_tick(self, tick: TickEvent) -> Optional[OrderRequest]:
        """Dispatch tick event to active engine based on real-time market regime."""
        # 1. Update Global Circuit Breaker
        self._update_global_circuit_breaker(tick.timestamp)

        # 2. Update Detectors
        regime_state: MarketRegimeState = self.regime_detector.update(tick.timestamp, tick.bid, tick.ask)
        range_state: RangeState = self.range_detector.update(tick.timestamp, tick.bid, tick.ask)

        # 3. Priority Dispatch: If an engine already has an active setup/campaign, let it manage!
        if self.engine_b.has_active_campaign:
            return self.engine_b.on_tick_with_regime(
                tick,
                regime_state,
                range_state.range_high,
                range_state.range_low,
            )

        if self.engine_a.layer_mgr.has_active_setup:
            return self.engine_a.on_tick(tick)

        # 4. Gating: Global Circuit Breaker Tripped -> Hold all new entries
        if self._circuit_breaker_tripped:
            return None

        # 5. Gating: Monday Filter, Time Blackout & Spread Filter
        if self.disable_monday and tick.timestamp.weekday() == 0:
            return None

        if tick.timestamp.hour in self.blackout_hours_utc or tick.spread > self.max_spread:
            return None

        # 6. Regime Dispatch: Decide which engine gets entry rights
        if regime_state.is_trending:
            # MARKET REGIME: STRONG TREND (EXPANSION)
            # Engine A is SLEEP / LOCKED
            # Engine B takes over the helm!
            return self.engine_b.on_tick_with_regime(
                tick,
                regime_state,
                range_state.range_high,
                range_state.range_low,
            )
        else:
            # MARKET REGIME: RANGE / SIDEWAY (CONSOLIDATION)
            # Engine B is SLEEP
            # Engine A is ACTIVE!
            return self.engine_a.on_tick(tick)

    def on_start(self):
        """Propagate start lifecycle."""
        self.engine_a.on_start()
        self.engine_b.on_start()

    def on_finish(self):
        """Propagate finish lifecycle."""
        self.engine_a.on_finish()
        self.engine_b.on_finish()
