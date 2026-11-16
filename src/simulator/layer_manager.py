"""Controlled 3-Layer Position Manager with Shared Invalidation SL, Dynamic BE Policies, and Session Sizing (TICK-302 / TICK-403)."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal, Optional
import uuid

from src.simulator.execution import OrderRequest
from src.simulator.portfolio import PortfolioTracker, Position
from src.strategies.base import TickEvent


class BEPolicy(str, Enum):
    """Dynamic Breakeven / Profit Protection Policy."""
    NONE = "NONE"             # Keep original hard invalidation SL
    STRICT = "STRICT"         # Move SL to Entry price once TP1 is hit
    BUFFER = "BUFFER"         # Move SL to Boundary price (RH/RL) once TP1 is hit
    STEP_LOCK = "STEP_LOCK"   # Leave SL until TP2, then lock runner to EQ


@dataclass
class LayerSetup:
    """Represents an active multi-layer trading campaign."""
    setup_id: str
    side: Literal["BUY", "SELL"]
    start_time: datetime
    hard_sl: float
    initial_hard_sl: float
    tp1_price: float
    tp2_price: float
    boundary_price: float = 0.0
    active_position_ids: list[str] = field(default_factory=list)
    tp1_hit: bool = False
    tp2_hit: bool = False
    is_closed: bool = False
    current_max_layers: int = 3
    current_volumes: list[float] = field(default_factory=list)
    layers_requested: int = 1


class LayerManager:
    """Coordinates controlled 1-3 layer entries, shared invalidation stop loss, and split exits."""

    def __init__(
        self,
        layer_volumes: Optional[list[float]] = None,
        layer_spacing_usd: float = 0.40,
        max_layers: int = 3,
        be_policy: str = "NONE",
    ):
        self.base_layer_volumes = layer_volumes or [0.05, 0.10, 0.15]
        self.layer_spacing_usd = layer_spacing_usd
        self.default_max_layers = min(max_layers, len(self.base_layer_volumes))
        self.be_policy = be_policy.upper()
        self.current_setup: Optional[LayerSetup] = None

    @property
    def has_active_setup(self) -> bool:
        return self.current_setup is not None and not self.current_setup.is_closed

    def start_setup(
        self,
        side: Literal["BUY", "SELL"],
        timestamp: datetime,
        hard_sl: float,
        tp1_price: float,
        tp2_price: float,
        boundary_price: float = 0.0,
        lot_multiplier: float = 1.0,
        max_layers: Optional[int] = None,
    ) -> OrderRequest:
        """Initiate Layer 1 entry for a new setup with dynamic session sizing."""
        setup_id = str(uuid.uuid4())[:8]

        eff_max_layers = max_layers if max_layers is not None else self.default_max_layers
        eff_volumes = [
            max(0.01, round(vol * lot_multiplier, 2))
            for vol in self.base_layer_volumes
        ]

        self.current_setup = LayerSetup(
            setup_id=setup_id,
            side=side,
            start_time=timestamp,
            hard_sl=hard_sl,
            initial_hard_sl=hard_sl,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            boundary_price=boundary_price,
            current_max_layers=eff_max_layers,
            current_volumes=eff_volumes,
        )

        vol = eff_volumes[0]
        return OrderRequest(
            order_type="OPEN",
            side=side,
            volume=vol,
            signal_time=timestamp,
            sl=hard_sl,
            tp=tp2_price,
            reason=f"LAYER_1_{side}",
        )

    def register_position(self, position_id: str):
        """Record opened position ID into active setup."""
        if self.current_setup and not self.current_setup.is_closed:
            if position_id not in self.current_setup.active_position_ids:
                self.current_setup.active_position_ids.append(position_id)

    def evaluate(self, tick: TickEvent, portfolio: PortfolioTracker) -> list[OrderRequest]:
        """Check all exit conditions (Hard SL, TP1, TP2) and secondary layer entries (Layer 2 & 3)."""
        orders: list[OrderRequest] = []
        if not self.has_active_setup:
            return orders

        setup = self.current_setup
        side = setup.side
        hard_sl = setup.hard_sl

        # Filter positions that are still genuinely open in portfolio
        open_pos_ids = [pid for pid in setup.active_position_ids if pid in portfolio.open_positions]
        setup.active_position_ids = open_pos_ids

        # If no positions remain open, close setup
        if not open_pos_ids:
            setup.is_closed = True
            return orders

        # -------------------------------------------------------------
        # 1. HARD / BREAKEVEN STOP LOSS (Liquidation of ALL remaining Layers)
        # -------------------------------------------------------------
        is_sl_hit = (tick.ask >= hard_sl) if side == "SELL" else (tick.bid <= hard_sl)
        if is_sl_hit:
            close_side = "BUY" if side == "SELL" else "SELL"
            reason_str = "BE_OR_BUFFER_SL" if setup.tp1_hit else "HARD_INVALIDATION_SL"
            for pid in open_pos_ids:
                pos = portfolio.open_positions[pid]
                orders.append(OrderRequest(
                    order_type="CLOSE",
                    side=close_side,
                    volume=pos.volume,
                    signal_time=tick.timestamp,
                    target_position_id=pid,
                    reason=reason_str,
                ))
            setup.is_closed = True
            return orders

        # -------------------------------------------------------------
        # 2. TAKE PROFIT EVALUATION (TP1: Equilibrium & TP2: Opposite Range)
        # -------------------------------------------------------------
        # Check TP1 (Garis tengah / Equilibrium 50% hit)
        is_tp1_hit = (tick.bid <= setup.tp1_price) if side == "SELL" else (tick.ask >= setup.tp1_price)
        if is_tp1_hit and not setup.tp1_hit:
            setup.tp1_hit = True
            close_side = "BUY" if side == "SELL" else "SELL"

            # If 2 or more layers were triggered, close the earliest layer at TP1
            if len(open_pos_ids) >= 2:
                pid_to_close = open_pos_ids[0]
                pos = portfolio.open_positions[pid_to_close]
                orders.append(OrderRequest(
                    order_type="CLOSE",
                    side=close_side,
                    volume=pos.volume,
                    signal_time=tick.timestamp,
                    target_position_id=pid_to_close,
                    reason="TP1_EQUILIBRIUM",
                ))
                open_pos_ids = open_pos_ids[1:]

            # Apply Dynamic Breakeven Policy on remaining positions
            first_pos = portfolio.open_positions[setup.active_position_ids[0]]
            first_entry_price = first_pos.open_price

            if self.be_policy == BEPolicy.STRICT.value:
                # Move SL to Entry Price
                setup.hard_sl = first_entry_price
                for pid in open_pos_ids:
                    if pid in portfolio.open_positions:
                        portfolio.open_positions[pid].sl = setup.hard_sl

            elif self.be_policy == BEPolicy.BUFFER.value:
                # Move SL to Boundary Price (giving retest room while slashing ~80% risk)
                if setup.boundary_price > 0:
                    if side == "SELL":
                        setup.hard_sl = round(setup.boundary_price + 0.15, 3)
                    else:
                        setup.hard_sl = round(setup.boundary_price - 0.15, 3)
                else:
                    # Fallback: midpoint between entry and initial SL
                    setup.hard_sl = round((first_entry_price + setup.initial_hard_sl) / 2.0, 3)

                for pid in open_pos_ids:
                    if pid in portfolio.open_positions:
                        portfolio.open_positions[pid].sl = setup.hard_sl

            # STEP_LOCK does not touch SL at TP1 (lets positions run unchoked)

        # Check TP2 (Batas seberang / Full Target)
        is_tp2_hit = (tick.bid <= setup.tp2_price) if side == "SELL" else (tick.ask >= setup.tp2_price)
        if is_tp2_hit:
            close_side = "BUY" if side == "SELL" else "SELL"

            if self.be_policy == BEPolicy.STEP_LOCK.value and len(open_pos_ids) > 1 and not setup.tp2_hit:
                # STEP_LOCK: Close Layer 2 at TP2, lock runner Layer 3 to TP1 (EQ)
                setup.tp2_hit = True
                pid_to_close = open_pos_ids[0]
                pos = portfolio.open_positions[pid_to_close]
                orders.append(OrderRequest(
                    order_type="CLOSE",
                    side=close_side,
                    volume=pos.volume,
                    signal_time=tick.timestamp,
                    target_position_id=pid_to_close,
                    reason="TP2_RUNNER_LOCK",
                ))
                setup.hard_sl = setup.tp1_price
                for pid in open_pos_ids[1:]:
                    if pid in portfolio.open_positions:
                        portfolio.open_positions[pid].sl = setup.hard_sl
                return orders
            else:
                for pid in open_pos_ids:
                    pos = portfolio.open_positions[pid]
                    orders.append(OrderRequest(
                        order_type="CLOSE",
                        side=close_side,
                        volume=pos.volume,
                        signal_time=tick.timestamp,
                        target_position_id=pid,
                        reason="TP2_OPPOSITE_RANGE",
                    ))
                setup.is_closed = True
                return orders

        # -------------------------------------------------------------
        # 3. SECONDARY LAYER ENTRY EVALUATION (Layer 2 & 3 Retest)
        # -------------------------------------------------------------
        current_layer_count = max(len(open_pos_ids), setup.layers_requested)
        if current_layer_count < setup.current_max_layers and not setup.tp1_hit:
            # Check price distance from initial entry
            first_pos = portfolio.open_positions[open_pos_ids[0]]
            first_entry_price = first_pos.open_price

            if side == "SELL":
                adverse_distance = tick.ask - first_entry_price
            else:
                adverse_distance = first_entry_price - tick.bid

            # Layer 2 Trigger
            if current_layer_count == 1 and adverse_distance >= self.layer_spacing_usd:
                setup.layers_requested = 2
                vol = setup.current_volumes[1]
                orders.append(OrderRequest(
                    order_type="OPEN",
                    side=side,
                    volume=vol,
                    signal_time=tick.timestamp,
                    sl=hard_sl,
                    tp=setup.tp2_price,
                    reason=f"LAYER_2_{side}_RETEST",
                ))

            # Layer 3 Trigger
            elif current_layer_count == 2 and adverse_distance >= (2.0 * self.layer_spacing_usd):
                setup.layers_requested = 3
                vol = setup.current_volumes[2]
                orders.append(OrderRequest(
                    order_type="OPEN",
                    side=side,
                    volume=vol,
                    signal_time=tick.timestamp,
                    sl=hard_sl,
                    tp=setup.tp2_price,
                    reason=f"LAYER_3_{side}_EXTREME",
                ))

        return orders
