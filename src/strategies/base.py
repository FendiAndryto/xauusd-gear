"""Base Strategy Interface for Tick-by-Tick Scalping."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import polars as pl

from src.simulator.execution import OrderRequest
from src.simulator.portfolio import PortfolioTracker


@dataclass
class TickEvent:
    """Represents a single arriving market tick."""
    timestamp: datetime
    bid: float
    ask: float
    spread: float
    volume: float
    flags: int


class BaseStrategy(ABC):
    """Abstract base class for all tick scalping strategies."""

    def __init__(self, name: str = "BaseStrategy"):
        self.name = name
        self.portfolio: Optional[PortfolioTracker] = None

    def set_portfolio(self, portfolio: PortfolioTracker):
        """Inject portfolio reference so strategy can check open positions."""
        self.portfolio = portfolio

    @abstractmethod
    def on_tick(self, tick: TickEvent) -> Optional[OrderRequest]:
        """Called on every single tick arrival.
        
        Args:
            tick: The latest tick event (timestamp, bid, ask, spread, volume, flags).
            
        Returns:
            Optional[OrderRequest] if strategy emits a trade signal, else None.
        """
        pass

    def on_start(self):
        """Lifecycle hook before backtest begins."""
        pass

    def on_finish(self):
        """Lifecycle hook after backtest completes."""
        pass
