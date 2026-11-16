"""TICK-SMC-06: Hybrid Profit Milestones & Extreme Sweep Wick SL Manager.

Monitors active positions, triggers breakeven (BEP) shift once Milestone 1 is reached,
and ensures runner positions lock in risk-free execution.
"""

from dataclasses import dataclass
from typing import Optional

from src.simulator.portfolio import PortfolioTracker, Position


class HybridExitManager:
    """Manages multi-milestone exits and dynamic Breakeven (BEP) adjustments."""

    def __init__(self, bep_buffer_usd: float = 0.15):
        self.bep_buffer_usd = bep_buffer_usd
        self.runner_positions_protected: set[str] = set()

    def update(
        self,
        portfolio: PortfolioTracker,
        current_bid: float,
        current_ask: float,
        equilibrium_level: float,
    ):
        """Inspect open positions and move SL to Breakeven once in substantial profit (>= 1.5R)."""
        for pos_id, pos in portfolio.open_positions.items():
            if pos_id in self.runner_positions_protected:
                continue

            # Need an initial SL to compute risk distance R
            if pos.sl is None:
                continue

            initial_risk = abs(pos.open_price - pos.sl)
            if initial_risk < 0.10:
                continue

            if pos.side == "BUY":
                # Must be in profit by at least 1.5R before locking BEP
                profit_dist = current_bid - pos.open_price
                if profit_dist >= (1.5 * initial_risk):
                    # Set SL to open_price + small buffer, but strictly below current bid
                    new_sl = round(pos.open_price + self.bep_buffer_usd, 2)
                    if new_sl < current_bid and new_sl > pos.sl:
                        pos.sl = new_sl
                        self.runner_positions_protected.add(pos_id)

            elif pos.side == "SELL":
                # Must be in profit by at least 1.5R before locking BEP
                profit_dist = pos.open_price - current_ask
                if profit_dist >= (1.5 * initial_risk):
                    # Set SL to open_price - small buffer, but strictly above current ask
                    new_sl = round(pos.open_price - self.bep_buffer_usd, 2)
                    if new_sl > current_ask and new_sl < pos.sl:
                        pos.sl = new_sl
                        self.runner_positions_protected.add(pos_id)

    def reset_day(self):
        """Clean up daily cache of protected position IDs."""
        self.runner_positions_protected.clear()
