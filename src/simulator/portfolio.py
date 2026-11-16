"""Account, Margin, and Position State Tracker for XAUUSD."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional
import uuid

from src.config import BrokerConfig


@dataclass
class Position:
    """Represents an active or closed trading position."""
    position_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    volume: float                  # In standard lots
    open_time: datetime
    open_price: float
    sl: Optional[float] = None
    tp: Optional[float] = None
    close_time: Optional[datetime] = None
    close_price: Optional[float] = None
    close_reason: Optional[str] = None
    commission: float = 0.0
    pnl_gross: float = 0.0
    pnl_net: float = 0.0
    comment: Optional[str] = None

    @property
    def is_open(self) -> bool:
        return self.close_time is None


@dataclass
class AccountSnapshot:
    """Point-in-time snapshot of account financial state."""
    timestamp: datetime
    balance: float
    equity: float
    used_margin: float
    free_margin: float
    margin_level_pct: float
    open_positions_count: int


class PortfolioTracker:
    """Tracks account balance, open positions, floating PnL, margin and trade history."""

    def __init__(self, initial_balance: float = 10_000.0, broker_config: Optional[BrokerConfig] = None):
        self.broker = broker_config or BrokerConfig()
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.open_positions: dict[str, Position] = {}
        self.closed_positions: list[Position] = []
        self.equity_history: list[AccountSnapshot] = []

    def open_position(
        self,
        side: Literal["BUY", "SELL"],
        volume: float,
        price: float,
        timestamp: datetime,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        commission: float = 0.0,
        comment: Optional[str] = None,
    ) -> Position:
        """Register a new open position."""
        pos_id = str(uuid.uuid4())[:8]
        pos = Position(
            position_id=pos_id,
            symbol=self.broker.symbol,
            side=side,
            volume=volume,
            open_time=timestamp,
            open_price=price,
            sl=sl,
            tp=tp,
            commission=commission,
            comment=comment,
        )
        self.open_positions[pos_id] = pos
        return pos

    def close_position(
        self,
        position_id: str,
        price: float,
        timestamp: datetime,
        reason: str = "SIGNAL",
        additional_commission: float = 0.0,
    ) -> Position:
        """Close an existing position and realize PnL."""
        if position_id not in self.open_positions:
            raise KeyError(f"Position {position_id} not found in open positions.")

        pos = self.open_positions.pop(position_id)
        pos.close_time = timestamp
        pos.close_price = price
        pos.close_reason = reason
        pos.commission += additional_commission

        # Compute Gross PnL
        # Contract size is 100 oz per lot for XAUUSD
        if pos.side == "BUY":
            price_diff = pos.close_price - pos.open_price
        else:
            price_diff = pos.open_price - pos.close_price

        pos.pnl_gross = round(price_diff * self.broker.contract_size * pos.volume, 2)
        pos.pnl_net = round(pos.pnl_gross - pos.commission, 2)

        # Update cash balance
        self.balance = round(self.balance + pos.pnl_net, 2)
        self.closed_positions.append(pos)
        return pos

    def update_tick(self, timestamp: datetime, bid: float, ask: float) -> AccountSnapshot:
        """Update floating PnL and account equity with the latest bid/ask tick."""
        floating_pnl = 0.0
        used_margin = 0.0

        for pos in self.open_positions.values():
            if pos.side == "BUY":
                # BUY closes at Bid
                diff = bid - pos.open_price
            else:
                # SELL closes at Ask
                diff = pos.open_price - ask

            pnl = diff * self.broker.contract_size * pos.volume
            floating_pnl += pnl

            # Margin requirement: (price * contract_size * volume) / leverage
            pos_margin = (pos.open_price * self.broker.contract_size * pos.volume) / self.broker.default_leverage
            used_margin += pos_margin

        equity = round(self.balance + floating_pnl, 2)
        free_margin = round(equity - used_margin, 2)
        margin_level = (equity / used_margin * 100.0) if used_margin > 0 else 0.0

        snapshot = AccountSnapshot(
            timestamp=timestamp,
            balance=self.balance,
            equity=equity,
            used_margin=used_margin,
            free_margin=free_margin,
            margin_level_pct=margin_level,
            open_positions_count=len(self.open_positions),
        )
        return snapshot
