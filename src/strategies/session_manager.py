"""Session-Aware Dynamic Risk and Regime Manager (TICK-401)."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SessionRegime:
    """Attributes governing trading behavior in a specific session window."""
    regime_name: str
    allow_new_entries: bool
    lot_multiplier: float
    max_layers: int
    is_rollover: bool


class SessionRegimeManager:
    """Classifies market hours (UTC) into risk regimes: Rollover, Asian, and London/NY Prime."""

    ROLLOVER_HOURS_UTC = {21, 22}
    ASIAN_HOURS_UTC = {23, 0, 1, 2, 3, 4, 5, 6}
    PRIME_HOURS_UTC = set(range(7, 21))

    def __init__(
        self,
        asian_lot_multiplier: float = 0.50,
        asian_max_layers: int = 2,
        prime_lot_multiplier: float = 1.00,
        prime_max_layers: int = 3,
    ):
        self.asian_lot_multiplier = asian_lot_multiplier
        self.asian_max_layers = asian_max_layers
        self.prime_lot_multiplier = prime_lot_multiplier
        self.prime_max_layers = prime_max_layers

    def get_regime(self, timestamp: datetime) -> SessionRegime:
        """Return the SessionRegime active at the given UTC timestamp."""
        hour = timestamp.hour

        # 1. Rollover Blackout: 21:00 - 22:59 UTC (04:00 - 06:00 WIB)
        # Broker spread widens dramatically ($0.58 - $0.68). No new entries permitted.
        if hour in self.ROLLOVER_HOURS_UTC:
            return SessionRegime(
                regime_name="ROLLOVER_BLACKOUT",
                allow_new_entries=False,
                lot_multiplier=0.0,
                max_layers=0,
                is_rollover=True,
            )

        # 2. Asian / Quiet Regime: 23:00 - 06:59 UTC (06:00 - 14:00 WIB)
        # Moderate range width, lower volume. Scaled risk (50% lot, max 2 layers).
        if hour in self.ASIAN_HOURS_UTC:
            return SessionRegime(
                regime_name="ASIAN_SCALED",
                allow_new_entries=True,
                lot_multiplier=self.asian_lot_multiplier,
                max_layers=self.asian_max_layers,
                is_rollover=False,
            )

        # 3. London / New York Prime Regime: 07:00 - 20:59 UTC (14:00 - 04:00 WIB)
        # Deep liquidity, rapid rejection dynamics. Full power (100% lot, full 3 layers).
        return SessionRegime(
            regime_name="LONDON_NY_PRIME",
            allow_new_entries=True,
            lot_multiplier=self.prime_lot_multiplier,
            max_layers=self.prime_max_layers,
            is_rollover=False,
        )
