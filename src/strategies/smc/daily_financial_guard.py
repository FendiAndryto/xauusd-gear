"""TICK-SMC-07: Daily Financial Guard (+10% Win Cap, Circuit Breaker, & Spread Guard).

Enforces institutional risk boundaries: locks profit on +10% daily gain,
trips circuit breaker on -7.5% to -12.5% daily drawdown, and guards against spread spikes.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Optional

from src.simulator.portfolio import PortfolioTracker


class GuardState(Enum):
    ACTIVE = "ACTIVE"
    DAILY_CAP_REACHED = "DAILY_CAP_REACHED"          # Reached +10% profit cap
    CIRCUIT_BREAKER_TRIPPED = "CIRCUIT_BREAKER_TRIPPED"  # Reached max daily loss
    SPREAD_TOO_HIGH = "SPREAD_TOO_HIGH"              # Spread > 3.5 pips


class TradingSession(Enum):
    ASIA = "ASIA"          # 00:00 - 07:00 UTC
    LONDON = "LONDON"      # 07:00 - 13:00 UTC
    NEW_YORK = "NEW_YORK"  # 13:00 - 21:00 UTC
    ROLLOVER = "ROLLOVER"  # 21:00 - 24:00 UTC


class DailyFinancialGuard:
    """Oversees day-by-day capital safety limits and session tagging."""

    def __init__(
        self,
        daily_profit_cap_pct: float = 0.10,    # +10.0%
        daily_loss_limit_pct: float = 0.10,    # -10.0% circuit breaker
        max_spread_pips: float = 3.5,          # 3.5 pips ($0.35 USD)
    ):
        self.daily_profit_cap_pct = daily_profit_cap_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_spread_pips = max_spread_pips

        self.current_date: Optional[date] = None
        self.starting_equity_today: float = 10_000.0
        self.state: GuardState = GuardState.ACTIVE

    def on_tick(
        self,
        timestamp: datetime,
        current_spread: float,
        portfolio: PortfolioTracker,
    ) -> GuardState:
        """Evaluate daily PnL and spread against risk rules."""
        tick_date = timestamp.date()

        # Day rollover check (00:00 UTC)
        if self.current_date is None or tick_date != self.current_date:
            self.current_date = tick_date
            self.starting_equity_today = portfolio.balance
            self.state = GuardState.ACTIVE

        # If already locked for the day, remain sleeping until midnight
        if self.state in (GuardState.DAILY_CAP_REACHED, GuardState.CIRCUIT_BREAKER_TRIPPED):
            return self.state

        # Check spread guard
        if current_spread > (self.max_spread_pips * 0.10):  # 3.5 pips = $0.35
            return GuardState.SPREAD_TOO_HIGH

        # Calculate today's realized + floating PnL
        daily_net_change = portfolio.balance - self.starting_equity_today

        # 1. Check Daily Profit Cap (+10%)
        profit_target_usd = self.starting_equity_today * self.daily_profit_cap_pct
        if daily_net_change >= profit_target_usd:
            self.state = GuardState.DAILY_CAP_REACHED
            return self.state

        # 2. Check Daily Drawdown Circuit Breaker (-10%)
        loss_limit_usd = -(self.starting_equity_today * self.daily_loss_limit_pct)
        if daily_net_change <= loss_limit_usd:
            self.state = GuardState.CIRCUIT_BREAKER_TRIPPED
            return self.state

        self.state = GuardState.ACTIVE
        return self.state

    @staticmethod
    def get_session(timestamp: datetime) -> TradingSession:
        """Identify trading session from UTC timestamp."""
        hour = timestamp.hour
        if 0 <= hour < 7:
            return TradingSession.ASIA
        elif 7 <= hour < 13:
            return TradingSession.LONDON
        elif 13 <= hour < 21:
            return TradingSession.NEW_YORK
        else:
            return TradingSession.ROLLOVER
