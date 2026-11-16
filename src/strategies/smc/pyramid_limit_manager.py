"""TICK-SMC-05: Layered Pyramid Limit Execution & Dynamic Cancellation Engine.

Manages 2-layer pending limit orders (1.0% at Open OB, 1.5% at 50% Mean Threshold),
computes precise lot sizing, splits orders for hybrid exit, and cancels orders on Opposite CHoCH.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

from src.simulator.execution import OrderRequest
from src.strategies.smc.order_block_mapper import OrderBlock


@dataclass
class LimitLayer:
    """An internal pending limit order waiting for price mitigation."""
    layer_id: str
    setup_id: str
    side: Literal["BUY", "SELL"]
    limit_price: float
    volume: float
    sl: float
    tp: float
    is_runner: bool  # True if runner to opposite boundary; False if Milestone 1 (50% Eq / 1:2 RR)
    created_time: datetime
    status: Literal["PENDING", "TRIGGERED", "CANCELLED"] = "PENDING"


class PyramidLimitManager:
    """Oversees limit order life cycle, risk sizing, and trigger events."""

    def __init__(
        self,
        risk_layer1_pct: float = 0.010,  # 1.0%
        risk_layer2_pct: float = 0.015,  # 1.5%
        spread_buffer_usd: float = 0.25,
        contract_size: float = 100.0,
        min_lot: float = 0.01,
        max_lot: float = 5.0,
    ):
        self.risk_layer1_pct = risk_layer1_pct
        self.risk_layer2_pct = risk_layer2_pct
        self.spread_buffer_usd = spread_buffer_usd
        self.contract_size = contract_size
        self.min_lot = min_lot
        self.max_lot = max_lot

        self.pending_layers: list[LimitLayer] = []
        self.active_setup_ids: set[str] = set()

    def create_pyramid_orders(
        self,
        ob: OrderBlock,
        current_time: datetime,
        equity: float,
        equilibrium_tp: float,
        opposite_boundary_tp: float,
    ) -> list[LimitLayer]:
        """Generate layered pending limit orders split into Milestone 1 and Runner."""
        setup_id = ob.ob_id
        if setup_id in self.active_setup_ids:
            return []

        self.active_setup_ids.add(setup_id)
        side = ob.side

        # -------------------------------------------------------------
        # 1. Determine Stop Loss with Spread Buffer & Scalp Bounds
        # -------------------------------------------------------------
        max_scalp_sl_usd = 3.50  # Max 35 pips for scalping
        min_scalp_sl_usd = 1.20  # Min 12 pips buffer against spread noise

        if side == "SELL":
            raw_sl = ob.extreme_wick_sl + self.spread_buffer_usd
            # Bound SL distance relative to entry
            sl_price = round(min(raw_sl, ob.open_price + max_scalp_sl_usd), 2)
            if sl_price - ob.open_price < min_scalp_sl_usd:
                sl_price = round(ob.open_price + min_scalp_sl_usd, 2)
        else:
            raw_sl = ob.extreme_wick_sl - self.spread_buffer_usd
            sl_price = round(max(raw_sl, ob.open_price - max_scalp_sl_usd), 2)
            if ob.open_price - sl_price < min_scalp_sl_usd:
                sl_price = round(ob.open_price - min_scalp_sl_usd, 2)

        created: list[LimitLayer] = []

        # -------------------------------------------------------------
        # 2. Layer 1 (Open OB - Risk 1.0%)
        # -------------------------------------------------------------
        dist1 = abs(ob.open_price - sl_price)
        if dist1 > 0.10:
            lot1_total = (equity * self.risk_layer1_pct) / (dist1 * self.contract_size)
            lot1_total = max(self.min_lot, min(self.max_lot, round(lot1_total, 2)))
            
            lot1_a = max(self.min_lot, round(lot1_total * 0.5, 2))
            lot1_b = max(self.min_lot, round(lot1_total - lot1_a, 2))

            # Directional Sanity Guard for TP1 and TP2
            if side == "BUY":
                tp1 = equilibrium_tp if equilibrium_tp > ob.open_price + (1.5 * dist1) else round(ob.open_price + (2.0 * dist1), 2)
                tp2 = opposite_boundary_tp if opposite_boundary_tp > tp1 else round(ob.open_price + (3.5 * dist1), 2)
            else:
                tp1 = equilibrium_tp if equilibrium_tp < ob.open_price - (1.5 * dist1) else round(ob.open_price - (2.0 * dist1), 2)
                tp2 = opposite_boundary_tp if opposite_boundary_tp < tp1 else round(ob.open_price - (3.5 * dist1), 2)

            # Sub-order A: Milestone 1 (Eq 50% / RR 1:2)
            created.append(LimitLayer(
                layer_id=f"{setup_id}_L1_TP1",
                setup_id=setup_id,
                side=side,
                limit_price=ob.open_price,
                volume=lot1_a,
                sl=sl_price,
                tp=tp1,
                is_runner=False,
                created_time=current_time,
            ))
            # Sub-order B: Milestone 2 Runner (Opposite Boundary / Expansion)
            created.append(LimitLayer(
                layer_id=f"{setup_id}_L1_RUNNER",
                setup_id=setup_id,
                side=side,
                limit_price=ob.open_price,
                volume=lot1_b,
                sl=sl_price,
                tp=tp2,
                is_runner=True,
                created_time=current_time,
            ))

        # -------------------------------------------------------------
        # 3. Layer 2 (50% Mean Threshold OB - Risk 1.5%)
        # -------------------------------------------------------------
        dist2 = abs(ob.mean_threshold_50 - sl_price)
        if dist2 > 0.10:
            lot2_total = (equity * self.risk_layer2_pct) / (dist2 * self.contract_size)
            lot2_total = max(self.min_lot, min(self.max_lot, round(lot2_total, 2)))

            lot2_a = max(self.min_lot, round(lot2_total * 0.5, 2))
            lot2_b = max(self.min_lot, round(lot2_total - lot2_a, 2))

            if side == "BUY":
                tp1_l2 = equilibrium_tp if equilibrium_tp > ob.mean_threshold_50 + (1.5 * dist2) else round(ob.mean_threshold_50 + (2.0 * dist2), 2)
                tp2_l2 = opposite_boundary_tp if opposite_boundary_tp > tp1_l2 else round(ob.mean_threshold_50 + (3.5 * dist2), 2)
            else:
                tp1_l2 = equilibrium_tp if equilibrium_tp < ob.mean_threshold_50 - (1.5 * dist2) else round(ob.mean_threshold_50 - (2.0 * dist2), 2)
                tp2_l2 = opposite_boundary_tp if opposite_boundary_tp < tp1_l2 else round(ob.mean_threshold_50 - (3.5 * dist2), 2)

            created.append(LimitLayer(
                layer_id=f"{setup_id}_L2_TP1",
                setup_id=setup_id,
                side=side,
                limit_price=ob.mean_threshold_50,
                volume=lot2_a,
                sl=sl_price,
                tp=tp1_l2,
                is_runner=False,
                created_time=current_time,
            ))
            created.append(LimitLayer(
                layer_id=f"{setup_id}_L2_RUNNER",
                setup_id=setup_id,
                side=side,
                limit_price=ob.mean_threshold_50,
                volume=lot2_b,
                sl=sl_price,
                tp=tp2_l2,
                is_runner=True,
                created_time=current_time,
            ))

        self.pending_layers.extend(created)
        return created

    def on_tick(
        self,
        current_time: datetime,
        bid: float,
        ask: float,
    ) -> list[OrderRequest]:
        """Check if price has mitigated pending limit levels and emit market open signals."""
        orders_to_open: list[OrderRequest] = []

        remaining: list[LimitLayer] = []
        for layer in self.pending_layers:
            if layer.status != "PENDING":
                continue

            triggered = False
            if layer.side == "BUY":
                # BUY limit fills when Ask touches or drops to limit price
                if ask <= layer.limit_price:
                    triggered = True
            elif layer.side == "SELL":
                # SELL limit fills when Bid touches or exceeds limit price
                if bid >= layer.limit_price:
                    triggered = True

            if triggered:
                layer.status = "TRIGGERED"
                orders_to_open.append(OrderRequest(
                    order_type="OPEN",
                    side=layer.side,
                    volume=layer.volume,
                    signal_time=current_time,
                    sl=layer.sl,
                    tp=layer.tp,
                    reason=f"{layer.layer_id}_FILL",
                ))
            else:
                remaining.append(layer)

        self.pending_layers = remaining
        return orders_to_open

    def cancel_on_opposite_choch(self, new_choch_side: Literal["BUY", "SELL"]) -> int:
        """Cancel all pending limits that run against the new structural direction."""
        cancelled_count = 0
        remaining: list[LimitLayer] = []

        for layer in self.pending_layers:
            # If new CHoCH is BULLISH, cancel any pending SELL limits (structure broken)
            # If new CHoCH is BEARISH, cancel any pending BUY limits
            if layer.side != new_choch_side:
                layer.status = "CANCELLED"
                cancelled_count += 1
            else:
                remaining.append(layer)

        self.pending_layers = remaining
        return cancelled_count

    def clear_all(self):
        """Cancel and purge all pending limits (e.g. at end of day or circuit breaker)."""
        self.pending_layers.clear()
        self.active_setup_ids.clear()
